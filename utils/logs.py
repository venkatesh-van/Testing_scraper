"""A ledger of everything that was NOT stored, and why.

Parts:
  log_not_stored(...)  call this from a spider when data is lost
  NotStoredLog         Scrapy extension: owns the CSV file, and by itself also
                       catches items dropped by pipelines and callbacks that crash
  summary              printed in the log when the spider closes

Output: data/logs/<spider>_<source_version>_not_stored.csv  (open it in Excel,
filter by `stage` or `reason`).
"""

import csv
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from itemadapter import ItemAdapter
from scrapy import signals

logger = logging.getLogger(__name__)

COLUMNS = ["logged_at", "run", "stage", "reason", "url", "lot_id", "detail"]

# Counted in the summary but not written to the CSV (not a problem, just a re-run).
COUNT_ONLY = {("storage", "already_stored")}

# DropItem message text -> (stage, reason)
DROP_REASONS = (
    ("no lot_id", "validation", "no_lot_id"),
    ("duplicate lot_id", "validation", "duplicate_lot_id"),
    ("already stored", "storage", "already_stored"),
)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_not_stored(owner, stage, reason, url=None, lot_id=None, detail=None):
    """Record one 'data lost' event. `owner` is the spider (or the crawler).

    Works without Scrapy running (unit tests): it then only writes a log line.
    """
    crawler = getattr(owner, "crawler", owner)
    ledger = getattr(crawler, "not_stored_log", None)
    if ledger is None:
        logger.warning("NOT STORED [%s/%s] lot_id=%s url=%s %s",
                       stage, reason, lot_id or "-", url or "-", detail or "")
        return
    ledger.record(stage, reason, url=url, lot_id=lot_id, detail=detail)


class NotStoredLog:
    def __init__(self, logs_dir, crawler=None):
        self.logs_dir = Path(logs_dir or "data/logs")
        self.crawler = crawler
        self.counts = Counter()
        self.file = None
        self.writer = None
        self.path = None
        self.run = now_iso()

    @classmethod
    def from_crawler(cls, crawler):
        ledger = cls(crawler.settings.get("LOGS_DIR"), crawler)
        crawler.not_stored_log = ledger  # log_not_stored() finds it here
        crawler.signals.connect(ledger.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ledger.item_dropped, signal=signals.item_dropped)
        crawler.signals.connect(ledger.spider_error, signal=signals.spider_error)
        crawler.signals.connect(ledger.spider_closed, signal=signals.spider_closed)
        return ledger

    # ---- file
    def spider_opened(self, spider):
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{spider.name}_{getattr(spider, 'source_version', 'run')}"
        self.path = self.logs_dir / f"{stem}_not_stored.csv"
        is_new = not self.path.exists() or self.path.stat().st_size == 0
        self.file = open(self.path, "a", newline="", encoding="utf-8-sig")
        self.writer = csv.DictWriter(self.file, COLUMNS)
        if is_new:
            self.writer.writeheader()
        self.run = now_iso()

    def record(self, stage, reason, url=None, lot_id=None, detail=None):
        self.counts[(stage, reason)] += 1
        if (stage, reason) in COUNT_ONLY:
            return
        logger.warning("NOT STORED [%s/%s] lot_id=%s url=%s %s",
                       stage, reason, lot_id or "-", url or "-", detail or "")
        if self.writer:
            text = " ".join(str(detail).split())[:500] if detail else None
            self.writer.writerow({"logged_at": now_iso(), "run": self.run, "stage": stage,
                                  "reason": reason, "url": url, "lot_id": lot_id, "detail": text})
            self.file.flush()  # a crash loses nothing

    # ---- things Scrapy tells us about by itself
    def item_dropped(self, item, response, exception, spider=None):
        """A pipeline raised DropItem (validation or storage)."""
        message = str(exception)
        stage, reason = "pipeline", "dropped"
        for text, found_stage, found_reason in DROP_REASONS:
            if text in message:
                stage, reason = found_stage, found_reason
                break
        row = ItemAdapter(item)
        self.record(stage, reason, url=row.get("lot_url") or getattr(response, "url", None),
                    lot_id=row.get("lot_id"), detail=message)

    def spider_error(self, failure, response, spider=None):
        """A callback crashed (a parser bug or a page layout we did not expect)."""
        self.record("callback_error", failure.type.__name__, url=getattr(response, "url", None),
                    detail=failure.getErrorMessage())

    # ---- summary
    def spider_closed(self, spider, reason):
        stats = getattr(self.crawler, "stats", None)
        stored = stats.get_value("item_scraped_count", 0) if stats else 0
        logger.info("=== NOT STORED SUMMARY (spider finished: %s) ===", reason)
        if reason != "finished":
            logger.warning("Spider stopped early (%s): everything after that was never requested.", reason)
        logger.info("Rows stored this run: %s", stored)
        if not self.counts:
            logger.info("Nothing was lost.")
        for (stage, why), count in sorted(self.counts.items()):
            logger.info("  %-16s %-26s %d", stage, why, count)
        if self.path:
            logger.info("Details, one line per lost item: %s", self.path)
        if self.file:
            self.file.close()
            self.file = self.writer = None