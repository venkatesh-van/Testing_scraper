"""Re-runs skip what the csv already has: whole auctions before any request, single lots before their page."""

import csv
import json
from pathlib import Path

from scrapy.http import HtmlResponse, Request, TextResponse

from config.settings import GRAPHQL_URL
from models.auction_lot import FIELDS
from spiders.recent_auctions import RecentAuctionsSpider

FIXTURES = Path(__file__).parent / "fixtures"
RESULTS = (FIXTURES / "results_page.html").read_text(encoding="utf-8")
RESULTS_URL = "https://www.sothebys.com/en/results"


def results_auctions(tmp_path):
    response = HtmlResponse(RESULTS_URL, body=RESULTS.encode(), encoding="utf-8", request=Request(RESULTS_URL))
    spider = RecentAuctionsSpider(raw_dir=tmp_path / "raw", processed_dir=tmp_path)
    return [r.cb_kwargs["auction"]["auction_url"] for r in spider.parse(response) if "auction" in r.cb_kwargs]


def write_csv(tmp_path, rows):
    with open(tmp_path / "recent_auctions_recent.csv", "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def make(tmp_path, **kwargs):
    return RecentAuctionsSpider(raw_dir=tmp_path / "raw", processed_dir=tmp_path, **kwargs)


def requested(spider):
    response = HtmlResponse(RESULTS_URL, body=RESULTS.encode(), encoding="utf-8", request=Request(RESULTS_URL))
    return [r.cb_kwargs["auction"]["auction_url"] for r in spider.parse(response) if "auction" in r.cb_kwargs]


def test_a_complete_stored_auction_is_skipped_and_does_not_use_up_max_auctions(tmp_path):
    first, second = results_auctions(tmp_path)[:2]
    write_csv(tmp_path, [{"lot_id": "a", "auction_url": first + "/"}, {"lot_id": "b", "auction_url": first}])
    spider = make(tmp_path, max_auctions="1")
    assert requested(spider) == [second]                          # the first NEW auction
    assert spider.counts["auctions_skipped_already_stored"] == 1


def test_a_partly_stored_auction_is_crawled_again(tmp_path):
    first = results_auctions(tmp_path)[0]
    write_csv(tmp_path, [{"lot_id": "a", "auction_url": first}])
    (tmp_path / "recent_auctions_recent_auction_totals.json").write_text(json.dumps({first: 5}))
    assert first in requested(make(tmp_path))                     # 1 of 5 stored: not complete


def test_recrawl_stored_and_an_empty_csv_skip_nothing(tmp_path):
    every = results_auctions(tmp_path)
    write_csv(tmp_path, [{"lot_id": "a", "auction_url": every[0]}])
    assert requested(make(tmp_path, recrawl_stored="1")) == every
    (tmp_path / "recent_auctions_recent.csv").unlink()
    assert requested(make(tmp_path)) == every


def graphql(spider, name, offset=0):
    auction = {"auction_name": "Sale X", "auction_url": "https://www.sothebys.com/en/buy/auction/2026/sale-x"}
    request = spider.graphql_request("auc-1", offset, auction)
    response = TextResponse(GRAPHQL_URL, body=(FIXTURES / name).read_bytes(), request=request, encoding="utf-8")
    return list(spider.parse_graphql(response, "auc-1", offset, auction)), auction


def test_stored_lots_get_no_lot_page_request_and_the_total_is_recorded(tmp_path):
    fresh = make(tmp_path, details="1")
    out, auction = graphql(fresh, "graphql_page_more.json")
    lot_pages = [r for r in out if isinstance(r, Request) and r.callback == fresh.parse_detail]
    stored_id = lot_pages[0].cb_kwargs["lot"].lot_id

    write_csv(tmp_path, [{"lot_id": stored_id, "auction_url": auction["auction_url"]}])
    spider = make(tmp_path, details="1")
    out, _ = graphql(spider, "graphql_page_more.json")
    ids = [r.cb_kwargs["lot"].lot_id for r in out if isinstance(r, Request) and r.callback == spider.parse_detail]
    assert stored_id not in ids and len(ids) == len(lot_pages) - 1
    assert spider.counts["lots_skipped_already_stored"] == 1
    totals = json.loads((tmp_path / "recent_auctions_recent_auction_totals.json").read_text())
    assert auction["auction_url"] in totals


# ---------------------------------------------------------------- StoredData on its own
from utils.stored_data import StoredData, norm_url  # noqa: E402


def test_norm_url():
    assert norm_url("https://x/a/?lotFilter=1#top") == norm_url("https://x/a") == "https://x/a"


def test_stored_data_reads_the_csv_and_saves_totals_at_once(tmp_path):
    write_csv(tmp_path, [{"lot_id": "a", "auction_url": "https://x/s1"}, {"lot_id": "b", "auction_url": "https://x/s1"}])
    path = tmp_path / "recent_auctions_recent.csv"
    stored = StoredData(path)
    assert stored.has_lot("a") and not stored.has_lot("z")
    assert stored.auction_complete("https://x/s1/")                 # no total saved: counts as complete
    stored.record_total("https://x/s1", 3)
    assert not StoredData(path).auction_complete("https://x/s1")    # 2 of 3: read back from the file
    assert not StoredData(path, enabled=False).has_lot("a")         # fresh csv / recrawl: nothing stored
