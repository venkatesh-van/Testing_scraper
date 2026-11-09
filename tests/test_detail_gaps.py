"""Blank detail fields: what is on the page, what the fallbacks recover, what is flagged."""

from pathlib import Path
from types import SimpleNamespace

from scrapy.http import HtmlResponse, Request
from scrapy.settings import Settings

from models.auction_lot import AuctionLot
from parsers.lot_detail_parser import analyse_detail, merge_detail
from parsers.lot_facts import infer_medium
from spiders.recent_auctions import RecentAuctionsSpider

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://www.sothebys.com/en/buy/auction/2026/sale/lot-1"


def page(html, url=URL, **meta):
    return HtmlResponse(url=url, body=html.encode("utf-8"), encoding="utf-8",
                        request=Request(url, meta=meta))


def og(text):
    return '<meta property="og:description" content="%s">' % text.replace("\n", "&lt;/p&gt;&lt;p&gt;").join(["&lt;p&gt;", "&lt;/p&gt;"])


SHELL = "<html><body><p>Please wait while we load the page</p></body></html>"


# ---------------------------------------------------------------- analyse_detail
def test_a_normal_page_has_no_gaps_and_no_flags():
    report = analyse_detail(page((FIXTURES / "lot_detail.html").read_text(encoding="utf-8")))
    assert report.complete and report.flags == [] and report.gaps == {}
    assert report.detail["dimensions"] and report.detail["medium"] == "oil on canvas"


def test_a_shell_page_is_incomplete_and_every_expected_field_is_marked_incomplete():
    report = analyse_detail(page(SHELL))
    assert report.complete is False
    assert report.gaps == {"description": "incomplete", "dimensions": "incomplete", "medium": "incomplete"}


def test_dimensions_and_medium_are_recovered_from_the_pages_description_section():
    html = (f"<html><head>{og('Artist<br>Title')}</head><body><h2>Lot Details</h2><h3>Description</h3>"
            "<p>Artist</p><p>Title</p><p>oil on canvas</p><p>100 by 80 cm.</p></body></html>")
    report = analyse_detail(page(html))
    assert report.detail["dimensions"] == "100 by 80 cm." and report.detail["medium"] == "oil on canvas"
    assert {"dimensions_from_page_text", "medium_from_page_text"} <= set(report.flags)
    assert "dimensions" not in report.gaps and "medium" not in report.gaps


def test_size_in_inches_only_is_kept_and_flagged():
    html = f"<html><head>{og('Artist<br>Title<br>oil on canvas<br>12 by 10 in.')}</head><body><h2>Lot Details</h2></body></html>"
    report = analyse_detail(page(html))
    assert report.detail["dimensions"] == "12 by 10 in."
    assert "dimensions_inches_only" in report.flags and "dimensions" not in report.gaps


def test_no_size_anywhere_is_absent_not_a_failure():
    html = f"<html><head>{og('Artist<br>A Chinese silver teapot')}</head><body><h2>Lot Details</h2></body></html>"
    report = analyse_detail(page(html))
    assert report.gaps["dimensions"] == "absent" and "dimensions_parse_failed" not in report.flags


def test_medium_is_inferred_from_up_to_three_lines_above_the_size_and_flagged():
    text = "Artist\nTitle\nink on paper\nframed\nwith certificate\n30 by 40 cm."
    assert infer_medium(text) == "ink on paper"
    assert infer_medium("Artist\nTitle\n30 by 40 cm.") is None
    report = analyse_detail(page(f"<html><head>{og(text.replace(chr(10), '<br>'))}</head><body><h2>Lot Details</h2></body></html>"))
    assert report.detail["medium"] == "ink on paper" and "medium_inferred" in report.flags


def test_description_falls_back_to_the_meta_description_and_is_flagged_partial():
    html = ('<html><head><meta name="description" content="A short summary"></head>'
            "<body><h2>Lot Details</h2></body></html>")
    report = analyse_detail(page(html))
    assert report.detail["description"] == "A short summary" and "description_partial" in report.flags


def test_a_heading_with_no_text_is_parse_failed():
    html = ("<html><body><h2>Lot Details</h2><h3>Description</h3><p>Artist</p>"
            "<h3>Provenance</h3><h3>Literature</h3><p>Catalogue, 2016</p></body></html>")
    report = analyse_detail(page(html))
    assert report.gaps["provenance"] == "parse_failed" and "provenance_parse_failed" in report.flags
    assert report.detail["literature"] == "Catalogue, 2016" and "literature" not in report.gaps


def test_merge_never_erases_what_the_lot_already_has():
    lot = AuctionLot(lot_id="a", description="keep me", dimensions="1 by 1 cm.")
    merge_detail(lot, page(SHELL))
    assert (lot.description, lot.dimensions) == ("keep me", "1 by 1 cm.")


# ---------------------------------------------------------------- the spider's retry decision
class Stats:
    def __init__(self):
        self.values = {}

    def inc_value(self, key, count=1, start=0, spider=None):
        self.values[key] = self.values.get(key, start) + count


def spider(tmp_path, with_crawler=True):
    s = RecentAuctionsSpider(raw_dir=tmp_path, details="1")
    if with_crawler:
        s.crawler = SimpleNamespace(settings=Settings({"SOFT_RETRY_TIMES": 2}), stats=Stats())
    return s


def parse(s, html, lot, **meta):
    request = Request(URL, meta=meta, cb_kwargs={"lot": lot})
    response = HtmlResponse(URL, body=html.encode(), encoding="utf-8", request=request)
    return list(s.parse_detail(response, lot))


def test_an_incomplete_page_is_fetched_again_with_the_same_lot(tmp_path):
    s, lot = spider(tmp_path), AuctionLot(lot_id="a", lot_status="hidden")
    out = parse(s, SHELL, lot)
    assert len(out) == 1 and isinstance(out[0], Request)
    assert out[0].meta["retry_times"] == 1 and out[0].cb_kwargs["lot"] is lot
    assert s.counts["detail_retries"] == 1


def test_after_the_last_retry_the_lot_is_still_stored_and_flagged(tmp_path):
    s, lot = spider(tmp_path), AuctionLot(lot_id="a", lot_status="hidden")
    out = parse(s, SHELL, lot, retry_times=2)
    assert out == [lot] and "detail_page_incomplete" in lot.data_quality_flags
    assert s.counts["detail_incomplete_after_retry"] == 1


def test_withdrawn_lots_are_not_retried(tmp_path):
    s, lot = spider(tmp_path), AuctionLot(lot_id="a", lot_status="withdrawn")
    assert parse(s, SHELL, lot) == [lot] and s.counts["detail_retries"] == 0


def test_a_blank_field_on_a_complete_page_does_not_cause_a_retry_when_field_retries_is_off(tmp_path):
    html = f"<html><head>{og('Artist<br>A Chinese silver teapot')}</head><body><h2>Lot Details</h2></body></html>"
    s, lot = spider(tmp_path), AuctionLot(lot_id="a", lot_status="hidden")
    s.field_retries = 0                                       # -a field_retries=0
    assert parse(s, html, lot) == [lot] and s.counts["detail_retries"] == 0
    assert s.counts["gap_dimensions_absent"] == 1 and s.counts["gap_medium_absent"] == 1


def test_empty_sections_on_a_complete_page_are_fetched_again_and_found_values_kept(tmp_path):
    html = f"<html><head>{og('Artist<br>A Chinese silver teapot')}</head><body><h2>Lot Details</h2></body></html>"
    s, lot = spider(tmp_path), AuctionLot(lot_id="a", lot_status="hidden")
    out = parse(s, html, lot)
    assert len(out) == 1 and isinstance(out[0], Request)              # provenance etc. empty -> try again
    assert out[0].meta["field_tries"] == 1 and out[0].cb_kwargs["lot"] is lot
    assert out[0].meta["field_saved"]["description"]                  # carried to the next try
    last = parse(s, html, lot, field_tries=s.field_retries, field_saved=out[0].meta["field_saved"])
    assert last == [lot] and lot.description                          # out of tries: stored as it is
    assert s.counts["absent_provenance"] == 1 and s.counts["field_retries"] == 1


def test_recovery_after_a_retry_is_counted(tmp_path):
    s, lot = spider(tmp_path), AuctionLot(lot_id="a", lot_status="hidden")
    parse(s, (FIXTURES / "lot_detail.html").read_text(encoding="utf-8"), lot, retry_times=1)
    assert s.counts["detail_recovered_by_retry"] == 1 and lot.dimensions


def test_without_a_crawler_nothing_is_retried(tmp_path):
    s, lot = spider(tmp_path, with_crawler=False), AuctionLot(lot_id="a", lot_status="hidden")
    assert parse(s, SHELL, lot) == [lot] and "detail_page_incomplete" in lot.data_quality_flags


# ---------------------------------------------------------------- fixes from the real Al Thani data
def test_a_glued_size_is_found_and_the_stored_description_is_unchanged():
    text = "Rectangular lapis lazuli card holder.\nMeasuring 90 x 55mmFrench assay mark for platinumCirca 1925"
    report = analyse_detail(page(f"<html><head>{og(text)}</head><body><h2>Lot Details</h2></body></html>"))
    assert report.detail["dimensions"] == "Measuring 90 x 55mm"
    assert "55mmFrench" in report.detail["description"]


def test_block_tags_end_a_line():
    html = ('<html><head><meta property="og:description" content="&lt;div&gt;A jade case&lt;/div&gt;'
            '&lt;div&gt;Measuring 85 x 50mm&lt;/div&gt;&lt;div&gt;Signed Cartier&lt;/div&gt;"></head>'
            '<body><h2>Lot Details</h2></body></html>')
    report = analyse_detail(page(html))
    assert report.detail["description"].split("\n") == ["A jade case", "Measuring 85 x 50mm", "Signed Cartier"]
    assert report.detail["dimensions"] == "Measuring 85 x 50mm"


def test_underscore_line_separates_english_from_french():
    text = "A gold snuff box\nlength 2⅜in.; 6cm\n____________________\nTabatière en or\nlongueur 6cm"
    report = analyse_detail(page(f"<html><head>{og(text)}</head><body><h2>Lot Details</h2></body></html>"))
    assert "Tabatière" not in report.detail["description_en"] and report.detail["dimensions"] == "length 2⅜in.; 6cm"


def test_related_literature_on_the_page_is_its_own_section():
    html = ("<html><head>" + og("Artist<br>A bronze") + "</head><body><h2>Lot Details</h2>"
            "<h3>Catalogue Note</h3><p>After the Roman marble.</p><p>RELATED LITERATURE</p>"
            "<p>F. Haskell, N. Penny, Taste and the Antique, 2024.</p><h3>Condition Report</h3></body></html>")
    report = analyse_detail(page(html))
    assert report.detail["literature"] == "F. Haskell, N. Penny, Taste and the Antique, 2024."
    assert report.detail["catalogue_note"] == "After the Roman marble."


def test_a_literature_sub_heading_inside_the_description_text_fills_literature():
    text = "Artist<br>A bronze<br>height 30cm<br>RELATED LITERATURE<br>Book C, p. 4."
    report = analyse_detail(page(f"<html><head>{og(text)}</head><body><h2>Lot Details</h2></body></html>"))
    assert report.detail["literature"] == "Book C, p. 4." and "literature_from_description" in report.flags


def test_headings_with_a_colon_or_other_names_are_read():
    html = ("<html><head>" + og("Artist<br>A vase") + "</head><body><h2>Lot Details</h2>"
            "<h3>Literature:</h3><p>Book A, p. 1.</p><h3>Exhibitions</h3><p>Paris, 1925.</p></body></html>")
    report = analyse_detail(page(html))
    assert report.detail["literature"] == "Book A, p. 1." and report.detail["exhibited"] == "Paris, 1925."


NEXT = """<script id="__NEXT_DATA__" type="application/json">%s</script>"""


def test_a_page_built_by_script_is_read_from_its_embedded_json():
    import json
    data = {"props": {"pageProps": {
        "seo": {"description": "Sotheby's auction house"},
        "related": [{"slug": {"lotSlug": "other-lot"}, "description": "<p>Another lot</p>"}],
        "lot": {"slug": {"lotSlug": "lot-1"}, "description": "<p>A gold snuff box</p><p>length 6cm</p>",
                "provenance": "<p>Private collection</p>", "literature": [{"html": "<p>Book B</p>"}]}}}}
    html = "<html><head></head><body><div id='__next'></div>" + NEXT % json.dumps(data) + "</body></html>"
    report = analyse_detail(page(html))
    assert report.complete
    assert report.detail["description"] == "A gold snuff box\nlength 6cm" and report.detail["dimensions"] == "length 6cm"
    assert report.detail["provenance"] == "Private collection" and report.detail["literature"] == "Book B"
    assert {"description_from_page_json", "provenance_from_page_json", "literature_from_page_json"} <= set(report.flags)


def test_a_year_followed_by_in_is_not_an_inch_size():
    text = "Artist\nA silver tureen\nmade 1920 in Paris"
    report = analyse_detail(page(f"<html><head>{og(text)}</head><body><h2>Lot Details</h2></body></html>"))
    assert report.detail["dimensions"] is None
