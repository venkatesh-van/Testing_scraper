"""Fill blank columns in a CSV you already have, by opening each lot page again.

    scrapy crawl repair_details -a source=data/processed/recent_auctions_recent.csv
    scrapy crawl repair_details -a source=data/processed/historical_auctions_historical.csv
    scrapy crawl repair_details -a source=... -a limit=20                   # a small trial first
    scrapy crawl repair_details -a source=... -a only=description,literature,dimensions
    scrapy crawl repair_details -a source=... -a retries=4                  # more tries per broken page
    scrapy crawl repair_details -a source=... -a offline=1                  # no requests: text in the csv only
    scrapy crawl repair_details -a source=... -a recheck=1                  # also lots checked before
    scrapy crawl repair_details -a source=... -a skip_withdrawn=1           # leave withdrawn lots out

What it does
  1. OFFLINE PASS (every run, no requests): fills blanks from text already in the csv, e.g.
     literature written under 'RELATED LITERATURE' in the catalogue note, or a size the old
     parser missed ('55mmFrench', '4in wide').
  2. PAGE PASS: picks the rows still blank in the chosen columns (withdrawn lots included;
     lots already checked are skipped) and opens each lot page. A page that looks incomplete is
     fetched again, up to `retries` times (default SOFT_RETRY_TIMES = 2). The page's visible
     text is read first, then the JSON the page embeds (for pages built by script).
     Older /ecatalogue/...lot.N.html pages (historical csv) are read with the legacy parser.
     Rows are matched by lot_id, or by lot_url when lot_id is empty (older lots often have no ID).
  3. Writes values ONLY into blank cells; existing values are never changed.
  4. Rewrites THE SOURCE CSV at the end. <name>.bak.csv is the ORIGINAL, copied once on the
     first run and never changed afterwards. <name>.repair_log.csv lists every cell filled.
"""

import csv
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import scrapy
from scrapy.spidermiddlewares.httperror import HttpError

from config.settings import RAW_DIR
from models.auction_lot import merge_flags
from parsers.legacy_detail import is_legacy_url, legacy_report
from parsers.lot_detail_parser import analyse_detail
from pipelines.storage import save_raw_response
from utils.completeness import REPORT_COLUMNS, print_completeness
from utils.logs import log_not_stored
from utils.repair import (CHECKED_FLAG, REPAIR_FIELDS, fill_blanks, is_blank, offline_fill, read_rows,
                          rows_needing_repair, write_rows)
from utils.retries import retry_request

LOG_COLUMNS = ("run_at", "lot_id", "lot_url", "column", "source", "value")


def row_key(row):
    """lot_id, or lot_url when the row has no ID (historical lots)."""
    return row.get("lot_id") or row.get("lot_url")


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "y")


class RepairDetailsSpider(scrapy.Spider):
    name = "repair_details"
    allowed_domains = ["www.sothebys.com"]
    source_version = "repair"
    custom_settings = {"ITEM_PIPELINES": {}}   # no items: the CSV is rewritten when the spider closes

    def __init__(self, source=None, only=None, limit=None, raw_dir=None, retries=None,
                 offline=None, recheck=None, skip_withdrawn=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not source:
            raise ValueError("repair_details needs -a source=path/to/file.csv")
        self.source = Path(source)
        if self.source.name.endswith(".bak.csv"):
            raise ValueError(f"{self.source.name} is the untouched backup. Repair the main csv instead "
                             f"({self.source.name.replace('.bak.csv', '.csv')}).")
        self.header, self.rows = read_rows(self.source)
        self.fields = tuple(name.strip() for name in only.split(",")) if only else REPAIR_FIELDS
        missing = [name for name in self.fields if name not in self.header]
        if missing:
            raise ValueError(f"columns not in {self.source.name}: {missing}")
        self.soft_retry_times = int(retries) if retries not in (None, "") else None
        self.offline = _truthy(offline)
        self.raw_dir = Path(raw_dir) if raw_dir else RAW_DIR / self.name
        self.counts = Counter()
        self.counts["rows_in_file"] = len(self.rows)
        self.run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.filled_log = []
        self.changed = False
        self.by_id = {row_key(row): row for row in self.rows if row_key(row)}   # lot_id, or lot_url when no ID

        # 1. offline pass: text that is already in the csv
        for row in self.rows:
            filled = offline_fill(row)
            if filled:
                self.changed = True
                self.counts["rows_improved_offline"] += 1
                self._log_fill(row, filled, "csv_text")

        # 2. which rows still need their page
        needing = rows_needing_repair(self.rows, self.fields, recheck=_truthy(recheck),
                                      skip_withdrawn=_truthy(skip_withdrawn))
        self.todo = [] if self.offline else needing[: int(limit) if limit else None]
        self.counts["rows_still_blank_before_pages"] = len(needing)
        self.counts["rows_to_fetch"] = len(self.todo)
        self.left_for_later = len(needing) - len(self.todo)

    def _log_fill(self, row, columns, source):
        for name in columns:
            self.counts[f"filled_{name}"] += 1
            self.filled_log.append({"run_at": self.run_at, "lot_id": row.get("lot_id"),
                                    "lot_url": row.get("lot_url"), "column": name, "source": source,
                                    "value": (row.get(name) or "")[:300]})

    # first requests (Scrapy 2.13+ uses start(), older versions start_requests())
    def first_requests(self):
        return [scrapy.Request(row["lot_url"], callback=self.parse_lot, errback=self.lot_failed,
                               cb_kwargs={"lot_id": row_key(row)}, dont_filter=True)
                for row in self.todo if row.get("lot_url") and row_key(row)]

    async def start(self):
        for request in self.first_requests():
            yield request

    def start_requests(self):
        return iter(self.first_requests())

    def parse_lot(self, response, lot_id):
        save_raw_response(self.raw_dir, response, "html", label="repair")
        row = self.by_id[lot_id]          # lot_id here is the row key: the lot_id, or the lot_url
        lot_id = row.get("lot_id") or None
        # historical rows point at older /ecatalogue/ pages: use the legacy reader for those
        if is_legacy_url(row.get("lot_url")):
            report = legacy_report(response)
            self.counts["legacy_pages"] += 1
        else:
            report = analyse_detail(response)
        tries = response.meta.get("retry_times", 0)

        if not report.complete:
            retry = retry_request(self, response.request, "lot_page_incomplete")
            if retry is not None:
                self.counts["page_retries"] += 1
                self.logger.warning("Lot page looks incomplete (try %s), trying again: %s", tries + 1, response.url)
                yield retry
                return
            self.counts["still_incomplete"] += 1
            row["data_quality_flags"] = merge_flags(row.get("data_quality_flags"), "detail_page_incomplete")
            self.changed = True
            log_not_stored(self, "repair", "page_incomplete", url=response.url, lot_id=lot_id,
                           detail=f"nothing usable on the page after {tries} retries; "
                                  f"the next run tries it again (it is not marked {CHECKED_FLAG})")
            return
        if tries:
            self.counts["recovered_by_retry"] += 1

        filled = fill_blanks(row, report.detail, report.flags)
        if filled:
            self.counts["rows_improved_from_page"] += 1
            self._log_fill(row, filled, "page")
        for name in self.fields:
            if is_blank(row.get(name)):
                self.counts[f"still_blank_{name}_{report.gaps.get(name, 'absent')}"] += 1
        # The page was read in full: blanks left now are what the page has. Do not fetch it again.
        row["data_quality_flags"] = merge_flags(row.get("data_quality_flags"), CHECKED_FLAG)
        self.changed = True

    def lot_failed(self, failure):
        status = failure.value.response.status if failure.check(HttpError) else None
        self.counts["page_failed"] += 1
        log_not_stored(self, "repair", f"http_{status}" if status else type(failure.value).__name__,
                       url=failure.request.url, lot_id=failure.request.cb_kwargs.get("lot_id"),
                       detail=repr(failure.value))

    def write_log(self):
        if not self.filled_log:
            return None
        path = self.source.with_name(self.source.stem + ".repair_log.csv")
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, LOG_COLUMNS)
            if new:
                writer.writeheader()
            writer.writerows(self.filled_log)
        return path

    def closed(self, reason):
        """Rewrite the CSV (after a one-time backup), then print what changed."""
        if self.changed:
            backup = self.source.with_name(self.source.stem + ".bak.csv")
            if not backup.exists():
                shutil.copy2(self.source, backup)       # the ORIGINAL, kept once
            write_rows(self.source, self.header, self.rows)
            log = self.write_log()
            self.logger.info("CHANGES WRITTEN TO %s. %s is the untouched original. %s cells filled this run%s.",
                             self.source, backup.name, len(self.filled_log),
                             f", listed in {log.name}" if log else "")
        else:
            self.logger.info("Nothing to change in %s.", self.source)
        if self.left_for_later:
            self.logger.warning("%s rows still need their page (limit or offline=1). Run again without "
                                "-a limit / -a offline to do them.", self.left_for_later)
        self.logger.info("Repair summary (%s): %s", reason, dict(sorted(self.counts.items())))
        self.print_completeness()

    def print_completeness(self):
        """Fill rate per column, printed at the end of every run."""
        columns = [name for name in dict.fromkeys(REPORT_COLUMNS + tuple(self.fields)) if name in self.header]
        absent = {key[len("still_blank_"):-len("_absent")]: value for key, value in self.counts.items()
                  if key.startswith("still_blank_") and key.endswith("_absent")}
        print_completeness(self.source.name, self.rows, columns, absent)