import csv
import json
from types import SimpleNamespace

import pytest
from scrapy.exceptions import DropItem

from models.auction_lot import FIELDS, AuctionLot
from pipelines.storage import StoragePipeline

SPIDER = SimpleNamespace(name="demo", source_version="t", logger=SimpleNamespace(info=lambda *a: None))


def run(tmp_path, lots, overwrite=False):
    pipe = StoragePipeline(tmp_path, overwrite=overwrite)
    pipe.open_spider(SPIDER)
    for lot in lots:
        try:
            pipe.process_item(lot, SPIDER)
        except DropItem:
            pass
    pipe.close_spider(SPIDER)
    return pipe


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_writes_header_once_and_blank_for_none_but_zero_kept(tmp_path):
    run(tmp_path, [AuctionLot(lot_id="a", artist="周春芽", estimate_low=0, lot_status="sold")])
    rows = read(tmp_path / "demo_t.csv")
    assert list(rows[0]) == FIELDS
    assert rows[0]["estimate_low"] == "0" and rows[0]["estimate_high"] == ""
    assert rows[0]["artist"] == "周春芽"


def test_rerun_resumes_without_duplicates_or_second_header(tmp_path):
    run(tmp_path, [AuctionLot(lot_id="a"), AuctionLot(lot_id="b")])
    pipe = run(tmp_path, [AuctionLot(lot_id="b"), AuctionLot(lot_id="c")])
    assert [r["lot_id"] for r in read(tmp_path / "demo_t.csv")] == ["a", "b", "c"]
    assert (pipe.written, pipe.skipped) == (1, 1)
    assert (tmp_path / "demo_t.csv").read_bytes().count(b"lot_id,") == 1


def test_overwrite_starts_fresh(tmp_path):
    run(tmp_path, [AuctionLot(lot_id="a")])
    run(tmp_path, [AuctionLot(lot_id="b")], overwrite=True)
    assert [r["lot_id"] for r in read(tmp_path / "demo_t.csv")] == ["b"]


def test_coverage_report(tmp_path):
    run(tmp_path, [AuctionLot(lot_id="a", lot_status="hidden", data_quality_flags="result_not_public", artist="X"),
                   AuctionLot(lot_id="b", lot_status="hidden", data_quality_flags="result_not_public")])
    report = json.loads((tmp_path / "demo_t_coverage.json").read_text(encoding="utf-8"))
    assert report["rows_written_this_run"] == 2 and report["rows_in_file"] == 2
    assert report["columns"]["artist"] == {"filled": 1, "fill_rate": 0.5}
    assert report["lot_status_counts"] == {"hidden": 2}
    assert report["quality_flag_counts"] == {"result_not_public": 2}


def test_rows_without_lot_id_are_kept_and_resumed_by_lot_url(tmp_path):
    run(tmp_path, [AuctionLot(lot_url="u1"), AuctionLot(lot_url="u2")])
    pipe = run(tmp_path, [AuctionLot(lot_url="u2"), AuctionLot(lot_url="u3")])
    rows = read(tmp_path / "demo_t.csv")
    assert [r["lot_url"] for r in rows] == ["u1", "u2", "u3"]
    assert all(r["lot_id"] == "" for r in rows)
    assert pipe.skipped == 1