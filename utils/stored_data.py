"""What a csv already holds, so a re-run skips it (decision D26).

    stored = StoredData(csv_path)                 # reads the csv + <csv>_auction_totals.json once
    stored.auction_complete(auction_url)          # every lot of this auction is in the csv?
    stored.has_lot(lot_id)                        # this lot is in the csv?
    stored.record_total(auction_url, total)       # remember the site's lot total, at once

"Complete" means: the csv has at least as many lots of the auction as the site's total, saved the
first time the auction was crawled. An auction from an older csv, with no saved total, counts as
complete (use -a recrawl_stored=1 if you know it is not).
"""

import csv
import json
import logging
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)


def norm_url(url):
    """An auction link without query, fragment or trailing slash, so equal auctions compare equal."""
    return (url or "").split("#")[0].split("?")[0].rstrip("/")


class StoredData:
    def __init__(self, csv_path=None, enabled=True):
        """csv_path None or enabled False (fresh csv, recrawl_stored): nothing counts as stored."""
        self.csv_path = Path(csv_path) if csv_path else None
        self.totals_path = (self.csv_path.with_name(self.csv_path.stem + "_auction_totals.json")
                            if self.csv_path else None)
        self.lot_ids = set()
        self.per_auction = Counter()       # norm_url(auction_url) -> lots stored
        self.totals = {}                   # norm_url(auction_url) -> the site's lot total
        if self.csv_path and enabled:
            self._load()

    def _load(self):
        if self.csv_path.exists():
            with open(self.csv_path, newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    if row.get("lot_id"):
                        self.lot_ids.add(row["lot_id"])
                        self.per_auction[norm_url(row.get("auction_url"))] += 1
        if self.totals_path.exists():
            try:
                self.totals = json.loads(self.totals_path.read_text(encoding="utf-8"))
            except ValueError:
                logger.warning("Could not read %s: every stored auction counts as complete", self.totals_path.name)
        logger.info("Already in %s: %d lots in %d auctions", self.csv_path.name, len(self.lot_ids),
                    len(self.per_auction))

    def has_lot(self, lot_id):
        return lot_id in self.lot_ids

    def auction_complete(self, auction_url):
        """True when every lot of this auction is already in the csv."""
        key = norm_url(auction_url)
        have = self.per_auction.get(key, 0)
        if not have:
            return False
        total = self.totals.get(key)
        return total is None or have >= int(total)

    def record_total(self, auction_url, total):
        """Remember the site's lot total for an auction, written at once (a crash must not lose it)."""
        if self.totals_path is None or total is None or not auction_url:
            return
        key = norm_url(auction_url)
        if self.totals.get(key) == total:
            return
        self.totals[key] = total
        self.totals_path.parent.mkdir(parents=True, exist_ok=True)
        self.totals_path.write_text(json.dumps(self.totals, indent=1, sort_keys=True), encoding="utf-8")
