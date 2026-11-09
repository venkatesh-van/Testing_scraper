"""Validate every row: strip text, drop unusable/duplicate lots, add quality flags and price rules."""

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem

from models.auction_lot import LOT_STATUSES, merge_flags
from utils.price_validation import check_sold_price


def is_url(value):
    return isinstance(value, str) and value.lower().startswith(("http://", "https://"))


def lot_key(row):
    """Key used to spot duplicates: the lot_id, or the lot_url when there is no ID."""
    return row.get("lot_id") or row.get("lot_url")


class ValidationPipeline:
    def __init__(self, stats=None):
        self.stats = stats
        self.seen = set()

    @classmethod
    def from_crawler(cls, crawler):
        return cls(stats=crawler.stats)

    def bump(self, key):
        if self.stats:
            self.stats.inc_value(key)

    def process_item(self, item, spider=None):
        row = ItemAdapter(item)

        for name, value in list(row.items()):
            if isinstance(value, str):
                row[name] = value.strip() or None

        flags = []

        # lot_id must be a real ID (e.g. N09375-lot11), never a URL.
        # A URL here means the parser could not build an ID: leave lot_id empty.
        if is_url(row.get("lot_id")):
            if not row.get("lot_url"):
                row["lot_url"] = row["lot_id"]  # keep the link in its own column
            row["lot_id"] = None
            flags.append("lot_id_missing")
            self.bump("validation/lot_id_url_cleared")

        key = lot_key(row)
        if not key:
            self.bump("validation/dropped_no_lot_id")
            raise DropItem("lot has no lot_id")
        if key in self.seen:
            self.bump("validation/dropped_duplicate")
            raise DropItem(f"duplicate lot_id: {key}")
        self.seen.add(key)

        low, high = row.get("estimate_low"), row.get("estimate_high")
        if low is not None and high is not None and low > high:
            flags.append("estimate_low_gt_high")
        # every sold-price rule (utils/price_validation.py): flagged price_error_<rule> / price_warn_<rule>
        price_check = check_sold_price(row)
        flags.extend(price_check.flags())
        for rule in price_check.errors:
            self.bump(f"validation/price_error_{rule}")
        if row.get("lot_status") not in LOT_STATUSES:
            flags.append("unknown_lot_status")

        row["data_quality_flags"] = merge_flags(row.get("data_quality_flags"), *flags) or None
        for flag in flags:
            self.bump(f"validation/flag_{flag}")
        self.bump("validation/passed")
        return item