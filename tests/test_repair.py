"""repair_details: fill blank cells of an existing csv, never overwrite, keep a backup."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from scrapy.http import HtmlResponse, Request
from scrapy.settings import Settings

from models.auction_lot import FIELDS
from spiders.repair_details import RepairDetailsSpider
from utils.repair import fill_blanks, is_blank, offline_fill, read_rows, rows_needing_repair, write_rows

FIXTURES = Path(__file__).parent / "fixtures"
GOOD = (FIXTURES / "lot_detail.html").read_text(encoding="utf-8")
SHELL = "<html><body><p>Please wait</p></body></html>"


def row(lot_id, **values):
    return {**{name: "" for name in FIELDS}, "lot_id": lot_id, "lot_url": f"https://www.sothebys.com/en/buy/auction/2026/s/{lot_id}",
            "lot_status": "hidden", **values}


def csv_file(tmp_path, rows):
    path = tmp_path / "lots.csv"
    write_rows(path, FIELDS, rows)
    return path


# ---------------------------------------------------------------- pure functions
def test_is_blank_treats_zero_as_a_value():
    assert is_blank("") and is_blank(None) and is_blank("  ") and not is_blank("0") and not is_blank(0)


def test_rows_needing_repair_includes_withdrawn_and_skips_complete_and_urlless_rows():
    rows = [row("a"), row("b", lot_status="withdrawn"),
            row("c", description="x", description_en="x", dimensions="1 cm"),
            row("d", lot_url=""), row("e", description="x", description_en="x")]
    assert [r["lot_id"] for r in rows_needing_repair(rows)] == ["a", "b", "e"]
    assert [r["lot_id"] for r in rows_needing_repair(rows, skip_withdrawn=True)] == ["a", "e"]
    assert [r["lot_id"] for r in rows_needing_repair(rows, ("medium",))] == ["a", "b", "c", "e"]


def test_fill_blanks_never_overwrites_and_adds_only_relevant_flags():
    target = row("a", description="OLD", dimensions="")
    filled = fill_blanks(target, {"description": "NEW", "dimensions": "5 by 5 cm.", "medium": "oil on canvas"},
                         ["dimensions_from_page_text", "medium_inferred", "provenance_parse_failed"])
    assert target["description"] == "OLD"                      # kept
    assert target["dimensions"] == "5 by 5 cm." and target["medium"] == "oil on canvas"
    assert filled == ["medium", "dimensions"] or set(filled) == {"medium", "dimensions"}
    flags = set(target["data_quality_flags"].split(";"))
    assert flags == {"dimensions_from_page_text", "medium_inferred", "provenance_parse_failed"}


def test_fill_blanks_ignores_flags_of_columns_that_stayed_blank_and_marks_detail_quality():
    target = row("a")
    filled = fill_blanks(target, {"description": "D", "dimensions": None}, ["dimensions_from_page_text"])
    assert filled == ["description"] and target["data_quality_flags"] == "" and target["parse_quality"] == "detail"


def test_csv_round_trip_keeps_chinese_text_and_column_order(tmp_path):
    path = csv_file(tmp_path, [row("a", artist="周春芽")])
    header, rows = read_rows(path)
    assert header == FIELDS and rows[0]["artist"] == "周春芽"


# ---------------------------------------------------------------- the spider
def make(tmp_path, rows, **kwargs):
    s = RepairDetailsSpider(source=csv_file(tmp_path, rows), raw_dir=tmp_path / "raw", **kwargs)
    s.crawler = SimpleNamespace(settings=Settings({"SOFT_RETRY_TIMES": 2}),
                                stats=SimpleNamespace(inc_value=lambda *a, **k: None))
    return s


def respond(s, lot_id, html, **meta):
    url = s.by_id[lot_id]["lot_url"]
    request = Request(url, meta=meta, cb_kwargs={"lot_id": lot_id})
    return list(s.parse_lot(HtmlResponse(url, body=html.encode(), encoding="utf-8", request=request), lot_id))


def test_needs_a_source_and_valid_columns(tmp_path):
    with pytest.raises(ValueError):
        RepairDetailsSpider()
    with pytest.raises(ValueError):
        make(tmp_path, [row("a")], only="colour")


def test_first_requests_cover_only_rows_with_gaps_and_limit_works(tmp_path):
    rows = [row("a"), row("b"), row("c", lot_status="withdrawn"), row("d", description="x", description_en="x", dimensions="1 cm")]
    assert [r.cb_kwargs["lot_id"] for r in make(tmp_path, rows).first_requests()] == ["a", "b", "c"]
    assert [r.cb_kwargs["lot_id"] for r in make(tmp_path, rows, skip_withdrawn="1").first_requests()] == ["a", "b"]
    assert len(make(tmp_path, rows, limit="1").first_requests()) == 1


def test_repair_fills_blanks_rewrites_the_csv_and_keeps_one_backup(tmp_path):
    s = make(tmp_path, [row("a", artist="X"), row("b", description="KEEP", description_en="KEEP", dimensions="")])
    respond(s, "a", GOOD)
    respond(s, "b", GOOD)
    s.closed("finished")
    _, rows = read_rows(s.source)
    by = {r["lot_id"]: r for r in rows}
    assert by["a"]["dimensions"] and by["a"]["medium"] == "oil on canvas" and by["a"]["artist"] == "X"
    assert by["b"]["description"] == "KEEP" and by["b"]["dimensions"]      # existing value kept, blank filled
    assert s.counts["rows_improved_from_page"] == 2 and s.counts["filled_dimensions"] == 2
    _, original = read_rows(tmp_path / "lots.bak.csv")
    assert original[0]["dimensions"] == "" and original[0]["description"] == ""   # the backup is the original

    s.changed = True
    s.closed("finished")                                                         # a second write keeps the FIRST backup
    assert read_rows(tmp_path / "lots.bak.csv")[1][0]["dimensions"] == ""


def test_an_incomplete_page_is_retried_then_flagged_and_nothing_is_overwritten(tmp_path):
    s = make(tmp_path, [row("a", artist="X")])
    out = respond(s, "a", SHELL)
    assert len(out) == 1 and isinstance(out[0], Request) and out[0].meta["retry_times"] == 1
    assert respond(s, "a", SHELL, retry_times=2) == []
    s.closed("finished")
    _, rows = read_rows(s.source)
    assert "detail_page_incomplete" in rows[0]["data_quality_flags"] and rows[0]["description"] == ""


def test_a_page_that_has_no_data_leaves_the_cell_blank_and_says_why(tmp_path):
    html = '<html><head><meta property="og:description" content="&lt;p&gt;Artist&lt;/p&gt;&lt;p&gt;A silver teapot&lt;/p&gt;"></head><body><h2>Lot Details</h2></body></html>'
    s = make(tmp_path, [row("a")])
    respond(s, "a", html)
    assert s.counts["still_blank_dimensions_absent"] == 1


def test_nothing_changed_means_no_rewrite_and_no_backup(tmp_path):
    s = make(tmp_path, [row("a", description="x", description_en="x", dimensions="1 cm")])
    s.closed("finished")
    assert not (tmp_path / "lots.bak.csv").exists()


# ---------------------------------------------------------------- offline pass, checked rows, retries, log
NOTE = "A long essay about the model.\nRELATED LITERATURE\nF. Haskell, N. Penny,\nTaste and the Antique, 2024, pp. 289-293."


def test_offline_fill_takes_literature_from_the_note_and_a_glued_size():
    target = row("a", description="Rectangular case.\nMeasuring 90 x 55mmFrench assay markCirca 1925",
                 description_en="Rectangular case.\nMeasuring 90 x 55mmFrench assay markCirca 1925",
                 catalogue_note=NOTE)
    filled = offline_fill(target)
    assert set(filled) == {"literature", "dimensions"}
    assert target["literature"].startswith("F. Haskell") and target["dimensions"] == "Measuring 90 x 55mm"
    assert target["catalogue_note"] == NOTE                                   # the note itself is kept
    assert "literature_from_note" in target["data_quality_flags"]


def test_offline_fill_never_overwrites():
    target = row("a", literature="KEEP", catalogue_note=NOTE, dimensions="KEEP", description_en="4 cm")
    assert offline_fill(target) == [] and target["literature"] == "KEEP"


def test_the_offline_pass_runs_without_requests_and_is_logged(tmp_path):
    s = make(tmp_path, [row("a", catalogue_note=NOTE)], offline="1")
    assert s.first_requests() == [] and s.counts["filled_literature"] == 1
    s.closed("finished")
    _, rows = read_rows(s.source)
    assert rows[0]["literature"].startswith("F. Haskell")
    _, log = read_rows(tmp_path / "lots.repair_log.csv")
    assert log[0]["column"] == "literature" and log[0]["source"] == "csv_text"


def test_a_row_read_in_full_is_marked_and_skipped_next_time_unless_recheck(tmp_path):
    html = '<html><head><meta property="og:description" content="&lt;p&gt;A silver teapot&lt;/p&gt;"></head><body><h2>Lot Details</h2></body></html>'
    s = make(tmp_path, [row("a")])
    respond(s, "a", html)
    s.closed("finished")
    assert "repair_checked" in read_rows(s.source)[1][0]["data_quality_flags"]
    assert make(tmp_path, read_rows(s.source)[1]).first_requests() == []
    assert len(make(tmp_path, read_rows(s.source)[1], recheck="1").first_requests()) == 1


def test_an_incomplete_page_is_not_marked_checked_so_the_next_run_tries_again(tmp_path):
    s = make(tmp_path, [row("a")])
    respond(s, "a", SHELL, retry_times=2)
    s.closed("finished")
    rows = read_rows(s.source)[1]
    assert "repair_checked" not in rows[0]["data_quality_flags"]
    assert len(make(tmp_path, rows).first_requests()) == 1


def test_retries_argument_overrides_soft_retry_times(tmp_path):
    s = make(tmp_path, [row("a")], retries="4")
    out = respond(s, "a", SHELL, retry_times=3)                 # 3 < 4: one more try
    assert len(out) == 1 and out[0].meta["retry_times"] == 4
    assert respond(s, "a", SHELL, retry_times=4) == []          # used up


def test_the_backup_cannot_be_used_as_the_source(tmp_path):
    path = tmp_path / "lots.bak.csv"
    write_rows(path, FIELDS, [row("a")])
    with pytest.raises(ValueError):
        RepairDetailsSpider(source=path)


def test_limit_reports_rows_left_for_later(tmp_path):
    s = make(tmp_path, [row("a"), row("b"), row("c")], limit="1")
    assert len(s.first_requests()) == 1 and s.left_for_later == 2


# The real page layout (from a screenshot of a Kunstkammer lot): heading in <p data-testid>, text in <p>s.
REAL = """<html><head></head><body>
<h2>Lot Details</h2><span role="link">Lire en français</span>
<p data-testid="lotDetailsDescription">Description</p>
<div><p>oval, the borders chased and embosses with busts and fruit, the centre of one with Alexander cutting the Gordian knot</p>
<p><br></p><p>62.7cm, 24¾in. long</p><p>4299gr., 138oz</p></div>
<div><p>Condition Report</p></div>
<p>Provenance</p><p>Private Collection;</p><p>Christie's, London, 13 September 2011, lot 129</p>
<p>Literature</p><p>Cowdray Catalogue, 1919, no. 1427.</p>
<p>Additional Notices &amp; Disclaimers</p><p>The export of this property from France ...</p>
</body></html>"""


def test_a_withdrawn_lot_with_a_real_page_is_filled(tmp_path):
    s = make(tmp_path, [row("a", lot_status="withdrawn")])
    assert len(s.first_requests()) == 1
    respond(s, "a", REAL)
    s.closed("finished")
    got = read_rows(s.source)[1][0]
    assert got["description"].startswith("oval, the borders") and got["dimensions"] == "62.7cm, 24¾in. long"
    assert got["provenance"].startswith("Private Collection;") and got["literature"] == "Cowdray Catalogue, 1919, no. 1427."
    assert "Additional Notices" not in got["literature"]
