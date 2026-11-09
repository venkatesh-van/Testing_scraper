import json
from datetime import date
from pathlib import Path

import pytest
import scrapy
from scrapy.exceptions import CloseSpider
from scrapy.http import Request, TextResponse
from scrapy.spidermiddlewares.httperror import HttpError

from config.settings import GRAPHQL_URL, PAGE_SIZE
from models.auction_lot import AuctionLot
from spiders.historical_auctions import HistoricalAuctionsSpider
from spiders.recent_auctions import RecentAuctionsSpider, build_results_url

FIXTURES = Path(__file__).parent / "fixtures"
AUCTION = {"auction_name": "Sale X"}


class FakeFailure:
    """Just enough of twisted's Failure for the errbacks."""

    def __init__(self, request, value=None):
        self.request, self.value = request, value

    def check(self, *types):
        return self.value is not None and isinstance(self.value, types)


def spider(tmp_path, **kwargs):
    return RecentAuctionsSpider(raw_dir=tmp_path, **kwargs)


def reply(name, spider_, offset=0):
    request = spider_.graphql_request("auc-1", offset, AUCTION)
    return TextResponse(GRAPHQL_URL, body=(FIXTURES / name).read_bytes(), request=request, encoding="utf-8")


def run(spider_, name, offset=0):
    return list(spider_.parse_graphql(reply(name, spider_, offset), "auc-1", offset, AUCTION))


def test_results_url_uses_day_month_year_and_matches_the_old_v1_url():
    url = build_results_url(date(2015, 8, 2), date(2015, 9, 1))
    assert "from=02%2F08%2F2015" in url and "to=01%2F09%2F2015" in url
    assert "f0=1438473600000-1441065600000" in url  # UTC midnights (v1 browser used IST)


def test_historical_requires_explicit_dates(tmp_path):
    with pytest.raises(ValueError):
        HistoricalAuctionsSpider(raw_dir=tmp_path)
    assert HistoricalAuctionsSpider(start_date="2015-08-01", end_date="2015-08-31", raw_dir=tmp_path).source_version == "historical"


def test_start_after_end_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        spider(tmp_path, start_date="2026-02-01", end_date="2026-01-01")


def test_first_page_yields_lots_and_requests_the_next_offset(tmp_path):
    s = spider(tmp_path)
    out = run(s, "graphql_page_more.json")
    lots = [o for o in out if isinstance(o, AuctionLot)]
    nxt = [o for o in out if isinstance(o, scrapy.Request)]
    assert [l.lot_id for l in lots] == ["lot-1", "lot-2"]
    assert len(nxt) == 1 and json.loads(nxt[0].body)["variables"]["offset"] == PAGE_SIZE
    assert nxt[0].dont_filter is True


def test_last_page_stops(tmp_path):
    out = run(spider(tmp_path), "graphql_page_last.json", offset=PAGE_SIZE)
    assert all(isinstance(o, AuctionLot) for o in out) and len(out) == 1


def test_duplicate_lots_are_emitted_once(tmp_path):
    s = spider(tmp_path)
    run(s, "graphql_page_last.json")
    assert run(s, "graphql_page_last.json") == []


def test_short_pagination_is_logged(tmp_path, caplog):
    with caplog.at_level("WARNING"):
        run(spider(tmp_path), "graphql_page_short.json")
    assert "Pagination ended at 1 of 5" in caplog.text


def test_details_mode_requests_lot_page_instead_of_yielding(tmp_path):
    out = run(spider(tmp_path, details="1"), "graphql_page_last.json")
    assert len(out) == 1 and isinstance(out[0], scrapy.Request)
    assert out[0].url.endswith("/artist-3-work-3") and "lot" in out[0].cb_kwargs


def test_failed_detail_page_still_yields_the_lot(tmp_path):
    s = spider(tmp_path, details="1")
    request = run(s, "graphql_page_last.json")[0]
    lot = list(s.detail_failed(FakeFailure(request)))[0]
    assert "detail_request_failed" in lot.data_quality_flags


def test_each_graphql_page_gets_its_own_raw_file(tmp_path):
    s = spider(tmp_path)
    run(s, "graphql_page_more.json", offset=0)
    run(s, "graphql_page_last.json", offset=PAGE_SIZE)
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_blocked_status_closes_the_spider(tmp_path):
    s = spider(tmp_path)
    request = Request(GRAPHQL_URL)
    response = TextResponse(GRAPHQL_URL, status=429, request=request)
    with pytest.raises(CloseSpider):
        s.request_failed(FakeFailure(request, HttpError(response)))


def test_other_failures_are_logged_not_fatal(tmp_path, caplog):
    request = Request(GRAPHQL_URL)
    with caplog.at_level("ERROR"):
        spider(tmp_path).request_failed(FakeFailure(request, RuntimeError("timeout")))
    assert "Request failed" in caplog.text
