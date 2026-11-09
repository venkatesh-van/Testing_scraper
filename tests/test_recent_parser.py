import json
from pathlib import Path

from parsers.common import to_int
from parsers.graphql_parser import find_lot_cards, first_large_image, parse_card, parse_connection

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_to_int_keeps_zero_and_reads_text():
    assert to_int(0) == 0 and to_int("0") == 0
    assert to_int("150,000") == 150000 and to_int("150000.0") == 150000
    assert to_int(None) is None and to_int("") is None and to_int("abc") is None


def test_zero_prices_are_not_missing_and_lot_number_is_text():
    lot = parse_card(load("lot_card.json"), {"auction_name": "Example"}, "fixture")
    assert (lot.estimate_low, lot.estimate_high, lot.sold_price) == (0, 0, 0)
    assert lot.lot_number == "12A"
    assert lot.lot_status == "sold" and lot.is_sold is True
    assert lot.auction_name == "Example" and lot.source_version == "fixture"


def test_hidden_closed_lot_is_not_unsold():
    card = load("lot_card.json")
    card["bidState"]["sold"] = {"__typename": "ResultHidden"}
    lot = parse_card(card, {}, "fixture")
    assert lot.lot_status == "hidden" and lot.is_sold is None
    assert "result_not_public" in lot.data_quality_flags


def test_status_unsold_upcoming_withdrawn():
    card = load("lot_card.json")
    card["bidState"]["sold"] = {"isSold": False}
    assert parse_card(card, {}, "x").lot_status == "unsold"
    card["bidState"] = {"isClosed": False, "sold": {}}
    assert parse_card(card, {}, "x").lot_status == "upcoming"
    card["withdrawnState"] = {"state": "Withdrawn"}
    assert parse_card(card, {}, "x").lot_status == "withdrawn"


def test_title_without_pipe_uses_creator_and_pipe_spacing_is_flexible():
    card = load("lot_card.json")
    card["title"] = "A Silver Tea Service"
    lot = parse_card(card, {}, "x")
    assert (lot.artist, lot.title) == ("Example Artist", "A Silver Tea Service")
    card["title"] = "Artist X|Work Y"
    lot = parse_card(card, {}, "x")
    assert (lot.artist, lot.title) == ("Artist X", "Work Y")


def test_estimate_upon_request_and_missing_fields_are_flagged_not_crashing():
    card = load("lot_card.json")
    card["estimateV2"] = {"__typename": "EstimateUponRequest"}
    card["slug"] = {}
    card["media"] = None
    lot = parse_card(card, {}, "x")
    assert lot.estimate_low is None and lot.image_url is None and lot.lot_url is None
    assert {"estimate_on_request", "lot_url_missing"} <= set(lot.data_quality_flags.split(";"))


def test_lot_url_and_image():
    page = parse_connection(load("graphql_page_more.json"))
    lot = parse_card(page["cards"][0], {}, "x")
    assert lot.lot_url == "https://www.sothebys.com/en/buy/auction/2026/sale-x/artist-1-work-1"
    assert lot.image_url == "l1.jpg" and first_large_image({}) is None
    assert lot.estimate_low == 100000 and lot.estimate_currency == "HKD"


def test_parse_connection_and_find_cards():
    page = parse_connection(load("graphql_page_more.json"))
    assert len(page["cards"]) == 2 and page["total"] == 100 and page["has_next"] is True
    assert len(list(find_lot_cards({"a": [{"b": load("lot_card.json")}]}))) == 1
    assert parse_connection({})["cards"] == []
