"""The file-wide price check (validate_prices.py) and the csv header migration."""

import csv

import pytest

from models.auction_lot import FIELDS
from pipelines.storage import migrate_header
from validate_prices import main, validate

SOLD = dict(lot_id="a", lot_number="1", lot_status="sold", is_sold="True", is_closed="True", reserve_met="True",
            sold_price="1890", sold_currency="EUR", estimate_low="1500", estimate_high="2000",
            estimate_currency="EUR", sold_price_source="graphql", result_label="Lot Sold", data_quality_flags="")


def rules(rows):
    return {rule for _, rule, _ in validate(rows)}


def test_a_clean_file_has_no_findings():
    assert rules([SOLD, dict(SOLD, lot_id="b", lot_status="hidden", is_sold="", sold_price="", sold_currency="",
                              sold_price_source="", result_label="")]) == set()


def test_file_wide_rules():
    assert "duplicate_lot_id" in rules([SOLD, dict(SOLD)])
    assert "price_source_unknown" in rules([dict(SOLD, sold_price_source="")])
    assert "label_unsold_but_status_sold" in rules([dict(SOLD, result_label="Lot Unsold")])


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def test_the_script_exits_1_on_an_error_and_writes_a_report(tmp_path):
    path = tmp_path / "lots.csv"
    write(path, FIELDS, [dict(SOLD, sold_currency="USD")])
    assert main([str(path)]) == 1
    report = list(csv.DictReader(open(tmp_path / "lots.price_check.csv", encoding="utf-8-sig")))
    assert report[0]["rule"] == "currency_differs_from_estimate"
    write(path, FIELDS, [SOLD])
    assert main([str(path)]) == 0


def test_an_old_csv_gets_the_new_columns_and_keeps_its_data(tmp_path):
    path = tmp_path / "old.csv"
    old = [name for name in FIELDS if name not in ("sold_price_source", "result_label")]
    write(path, old, [{"lot_id": "a", "title": "T", "data_quality_flags": "x"}])
    assert migrate_header(path) is True
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    assert list(rows[0]) == FIELDS and rows[0]["title"] == "T" and rows[0]["result_label"] == ""
    assert (tmp_path / "old.before_new_columns.csv").exists()
    assert migrate_header(path) is False                     # already current: nothing to do


def test_an_unknown_column_with_data_is_never_dropped(tmp_path):
    path = tmp_path / "odd.csv"
    write(path, FIELDS + ["my_notes"], [{"lot_id": "a", "my_notes": "mine"}])
    with pytest.raises(RuntimeError):
        migrate_header(path)


def test_an_empty_removed_column_is_dropped(tmp_path):
    path = tmp_path / "had_login_columns.csv"
    write(path, FIELDS + ["condition_report", "auction_closed_at"], [{"lot_id": "a", "title": "T"}])
    assert migrate_header(path) is True
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    assert list(rows[0]) == FIELDS and rows[0]["title"] == "T"
