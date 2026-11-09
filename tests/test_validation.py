import pytest
from scrapy.exceptions import DropItem

from models.auction_lot import AuctionLot, merge_flags
from pipelines.validation import ValidationPipeline


def process(pipe, **fields):
    return pipe.process_item(AuctionLot(**fields), spider=None)


def test_drops_missing_and_duplicate_lot_ids():
    pipe = ValidationPipeline()
    with pytest.raises(DropItem):
        process(pipe, lot_id=None)
    with pytest.raises(DropItem):
        process(pipe, lot_id="   ")
    process(pipe, lot_id="a", lot_status="hidden")
    with pytest.raises(DropItem):
        process(pipe, lot_id="a", lot_status="hidden")


def test_url_in_lot_id_is_cleared_and_row_kept():
    url = "https://www.sothebys.com/en/auctions/ecatalogue/2015/crossroads-wei-dong-hk0614/lot.12.html"
    pipe = ValidationPipeline()
    lot = process(pipe, lot_id=url, lot_url=url, lot_status="unknown")
    assert lot.lot_id is None and lot.lot_url == url
    assert "lot_id_missing" in lot.data_quality_flags
    with pytest.raises(DropItem):  # same lot again -> duplicate (matched on lot_url)
        process(pipe, lot_id=url, lot_url=url, lot_status="unknown")
    other = url.replace("lot.12", "lot.11")
    assert process(pipe, lot_id=other, lot_url=other, lot_status="unknown").lot_id is None


def test_real_lot_id_is_kept():
    lot = process(ValidationPipeline(), lot_id="N09375-lot11", lot_status="unknown")
    assert lot.lot_id == "N09375-lot11"


def test_flags_bad_values():
    lot = process(ValidationPipeline(), lot_id="a", estimate_low=10, estimate_high=5,
                  sold_price=-1, lot_status="sold")
    flags = set(lot.data_quality_flags.split(";"))
    assert "estimate_low_gt_high" in flags and "price_error_not_positive" in flags


def test_sold_without_price_and_unknown_status():
    lot = process(ValidationPipeline(), lot_id="a", lot_status="sold")
    assert lot.data_quality_flags == "price_error_sold_without_price"
    assert "unknown_lot_status" in process(ValidationPipeline(), lot_id="b", lot_status="weird").data_quality_flags


def test_zero_is_valid_and_text_is_stripped():
    lot = process(ValidationPipeline(), lot_id=" a ", artist="  Name  ", estimate_low=0,
                  estimate_high=0, lot_status="hidden")
    assert lot.lot_id == "a" and lot.artist == "Name" and lot.estimate_low == 0
    assert lot.data_quality_flags is None  # nothing wrong -> no flags


def test_a_good_sold_price_passes_and_a_bad_one_is_flagged():
    good = dict(lot_id="a", lot_status="sold", is_sold=True, is_closed=True, sold_price=1890,
                sold_currency="EUR", estimate_low=1500, estimate_high=2000, estimate_currency="EUR")
    assert process(ValidationPipeline(), **good).data_quality_flags is None
    bad = process(ValidationPipeline(), **dict(good, lot_id="b", sold_currency="USD"))
    assert "price_error_currency_differs_from_estimate" in bad.data_quality_flags


def test_existing_flags_are_kept_without_repeats():
    assert merge_flags("a;b", "b", "c") == "a;b;c" and merge_flags(None) == ""