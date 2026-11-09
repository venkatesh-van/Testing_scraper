from pathlib import Path

from scrapy.http import HtmlResponse

from parsers.legacy_detail import is_legacy_url, legacy_report

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://www.sothebys.com/en/auctions/ecatalogue/2015/ming-furniture-the-dr-s-y-yip-collection-hk0624/lot.1.html"


def page(name, body=None):
    return HtmlResponse(url=URL, body=body or (FIXTURES / name).read_bytes(), encoding="utf-8")


def test_is_legacy_url():
    assert is_legacy_url(URL)
    assert not is_legacy_url("https://www.sothebys.com/en/buy/auction/2025/x/lot-1")
    assert not is_legacy_url(None)


def test_legacy_report_reads_paragraph_page():
    report = legacy_report(page("legacy_lot_paragraphs.html"))
    assert report.complete
    assert report.detail["description"].startswith("The top of standard mitre")
    assert "Grace Wu Bruce" in report.detail["literature"]
    assert report.detail["estimate_low"] == "4800000"
    assert report.gaps["provenance"] == "absent"   # this lot has no Provenance section


def test_empty_page_is_incomplete():
    report = legacy_report(page(None, body=b"<html><body><p>Access denied</p></body></html>"))
    assert not report.complete
    assert not any(name in report.detail for name in ("description", "provenance", "literature",
                                                       "exhibited", "catalogue_note"))
    assert report.detail["lot_id"] == "HK0624-lot1"   # still known from the link