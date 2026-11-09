import csv
from types import SimpleNamespace

from scrapy.exceptions import DropItem
from scrapy.http import Request

from models.auction_lot import AuctionLot
from spiders.recent_auctions import RecentAuctionsSpider
from utils.logs import NotStoredLog
from utils.retries import retry_request


def make_log(tmp_path):
    crawler = SimpleNamespace(stats=SimpleNamespace(get_value=lambda key, default=0: default))
    log = NotStoredLog(tmp_path, crawler)
    log.spider_opened(SimpleNamespace(name="demo", source_version="t"))
    return log


def test_ledger_writes_csv_and_counts(tmp_path):
    log = make_log(tmp_path)
    log.record("pagination", "ended_early", url="u", detail="got 1 of 5")
    log.record("storage", "already_stored", lot_id="a")  # counted, not written
    log.spider_closed(SimpleNamespace(name="demo"), "finished")
    with open(tmp_path / "demo_t_not_stored.csv", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1 and rows[0]["reason"] == "ended_early"
    assert log.counts[("storage", "already_stored")] == 1


def test_dropped_items_get_a_reason(tmp_path):
    log = make_log(tmp_path)
    log.item_dropped(AuctionLot(lot_id="a"), None, DropItem("duplicate lot_id: a"))
    log.item_dropped(AuctionLot(), None, DropItem("lot has no lot_id"))
    assert log.counts[("validation", "duplicate_lot_id")] == 1
    assert log.counts[("validation", "no_lot_id")] == 1


def test_soft_retry_needs_a_crawler(tmp_path):
    s = RecentAuctionsSpider(raw_dir=tmp_path)
    assert retry_request(s, Request("https://example.com"), "no_next_data") is None