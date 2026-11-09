"""Write rows to CSV as they arrive, plus raw responses and a coverage report."""

import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem

from models.auction_lot import FIELDS
from pipelines.validation import lot_key


def save_raw_response(raw_dir, response, extension, label=""):
    """Keep the exact response body so a parser fix never needs a re-crawl.

    The file name hashes URL + request body: every GraphQL page shares one URL,
    so hashing the URL alone would overwrite each page with the next.
    """
    body = response.request.body if response.request is not None else b""
    digest = hashlib.sha256(response.url.encode() + (body or b"")).hexdigest()[:16]
    name = f"{label}_{digest}.{extension}" if label else f"{digest}.{extension}"
    path = Path(raw_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.body)
    return path


def migrate_header(path):
    """Bring an older csv up to the current columns (models.auction_lot.FIELDS).

    * new columns are added (empty) in their right place, so values never shift columns
    * a column the model no longer has is dropped ONLY if it is empty in every row;
      a removed column that still holds data stops the run (RuntimeError), nothing is lost
    * the file as it was is copied once to <name>.before_new_columns.csv
    Returns True when the file was rewritten, False when it was already current.
    """
    path = Path(path)
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or [])
        rows = list(reader)
    if header == list(FIELDS):
        return False
    extra = [name for name in header if name not in FIELDS]
    with_data = [name for name in extra if any((row.get(name) or "").strip() for row in rows)]
    if with_data:
        raise RuntimeError(f"{path.name} has columns the model does not know, with data in them: {with_data}. "
                           f"Move or rename them before crawling into this file.")
    backup = path.with_name(path.stem + ".before_new_columns.csv")
    if not backup.exists():
        shutil.copy2(path, backup)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({name: row.get(name, "") for name in FIELDS} for row in rows)
    return True


class StoragePipeline:
    """One CSV per spider + source_version. Re-running resumes: stored lot_ids are skipped."""

    def __init__(self, processed_dir, overwrite=False, crawler=None):
        self.processed_dir = Path(processed_dir)
        self.overwrite = overwrite
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings.get("PROCESSED_DIR"), crawler.settings.getbool("OVERWRITE"), crawler)

    # `spider=None`: older Scrapy passes the spider, newer Scrapy does not (it is
    # then read from the crawler). Both work, with no deprecation warning.
    def _spider(self, spider):
        return spider or self.crawler.spider

    def open_spider(self, spider=None):
        spider = self._spider(spider)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{spider.name}_{getattr(spider, 'source_version', 'run')}"
        self.path = self.processed_dir / f"{stem}.csv"
        self.report_path = self.processed_dir / f"{stem}_coverage.json"
        if self.overwrite and self.path.exists():
            self.path.unlink()

        self.stored_ids = set()
        if self.path.exists() and self.path.stat().st_size and migrate_header(self.path):
            spider.logger.info("Added the new columns to %s (old file kept as *.before_new_columns.csv)", self.path)
        if self.path.exists():
            with open(self.path, newline="", encoding="utf-8-sig") as existing:
                rows = list(csv.DictReader(existing))
            self.stored_ids = {lot_key(row) for row in rows}
            self.rows_before = len(rows)
        else:
            self.rows_before = 0

        self.file = open(self.path, "a", newline="", encoding="utf-8-sig")  # BOM: Excel + Chinese
        self.writer = csv.DictWriter(self.file, FIELDS, extrasaction="ignore")
        if not self.rows_before and self.path.stat().st_size == 0:
            self.writer.writeheader()

        self.written = 0
        self.skipped = 0
        self.filled = Counter()
        self.statuses = Counter()
        self.flags = Counter()

    def process_item(self, item, spider=None):
        row = ItemAdapter(item)
        key = lot_key(row)
        if key in self.stored_ids:
            self.skipped += 1
            raise DropItem(f"already stored: {key}")
        self.stored_ids.add(key)

        self.writer.writerow({name: row.get(name) for name in FIELDS})
        self.file.flush()  # a crash loses at most the row in flight

        self.written += 1
        for name in FIELDS:
            if row.get(name) not in (None, ""):
                self.filled[name] += 1
        self.statuses[row.get("lot_status")] += 1
        for flag in (row.get("data_quality_flags") or "").split(";"):
            if flag:
                self.flags[flag] += 1
        return item

    def close_spider(self, spider=None):
        spider = self._spider(spider)
        self.file.close()
        total = self.written or 1
        report = {
            "spider": spider.name,
            "source_version": getattr(spider, "source_version", None),
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "csv_file": str(self.path),
            "rows_written_this_run": self.written,
            "rows_skipped_already_stored": self.skipped,
            "rows_in_file": self.rows_before + self.written,
            "note": "fill rates cover rows written in this run only",
            "lot_status_counts": dict(self.statuses),
            "quality_flag_counts": dict(self.flags),
            "columns": {
                name: {"filled": self.filled[name], "fill_rate": round(self.filled[name] / total, 4)}
                for name in FIELDS
            },
        }
        self.report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        spider.logger.info("Coverage report written to %s", self.report_path)
