from pathlib import Path

from scrapy.http import HtmlResponse

from parsers.html_parser import (legacy_lot_links, legacy_next_page, parse_auction_cards,
                                 parse_auction_dates, parse_legacy_lot)
from parsers.lot_detail_parser import (extract_facts, merge_detail, parse_lot_detail,
                                       parse_result_box)
from models.auction_lot import AuctionLot

FIXTURES = Path(__file__).parent / "fixtures"
LEGACY_URL = "https://www.sothebys.com/en/auctions/ecatalogue/2015/jim-thorell-7-paintings-n09375/lot.11.html"


def page(name, url="https://www.sothebys.com/en/results"):
    return HtmlResponse(url=url, body=(FIXTURES / name).read_bytes(), encoding="utf-8")


def test_auction_dates():
    assert parse_auction_dates("29 September–5 October 2026 | 3:00 PM HKT") == ("2026-09-29", "2026-10-05")
    assert parse_auction_dates("9 October 2026") == ("2026-10-09", "2026-10-09")
    assert parse_auction_dates("29–30 September 2026") == ("2026-09-29", "2026-09-30")
    assert parse_auction_dates("30 December–2 January 2027") == ("2026-12-30", "2027-01-02")
    assert parse_auction_dates("no date here") == (None, None)
    assert parse_auction_dates(None) == (None, None)


def test_results_page_cards_skip_cards_without_link():
    cards = parse_auction_cards(page("results_page.html"))
    assert [c["auction_name"] for c in cards] == ["Contemporary Day Auction", "Jim Thorell: 7 Paintings"]
    assert cards[0]["auction_date"] == "2026-09-29"
    assert cards[0]["auction_url"].endswith("/en/buy/auction/2026/contemporary-day-auction-4")
    assert cards[1]["auction_url"].endswith(".html")


def test_legacy_links_deduplicate_and_next_page():
    response = page("legacy_auction.html", "https://www.sothebys.com/en/auctions/2015/x.html")
    links = legacy_lot_links(response)
    assert len(links) == 2 and links[0].endswith("lot.1.html")
    assert legacy_next_page(response).endswith("?page=2")


def test_legacy_lot_reads_same_schema():
    lot = parse_legacy_lot(page("legacy_lot.html", LEGACY_URL), {"auction_name": "Jim Thorell: 7 Paintings"}, "t")
    assert (lot.lot_number, lot.sale_number, lot.lot_id) == ("11", "N09375", "N09375-lot11")
    assert (lot.artist, lot.title) == ("Jim Thorell", "Untitled (Red)")
    assert (lot.estimate_low, lot.estimate_high, lot.estimate_currency) == (8000, 12000, "USD")
    assert (lot.sold_price, lot.sold_currency, lot.lot_status) == (15000, "USD", "sold")
    assert lot.medium == "acrylic on canvas" and lot.year_created == 2015
    assert "194.3 by 139.7 cm" in lot.dimensions
    assert lot.parse_quality == "legacy" and "legacy_layout_unverified" in lot.data_quality_flags


def test_extract_facts_missing_data_stays_none():
    assert extract_facts("") == {"dimensions": None, "medium": None, "year_created": None}


def test_lot_detail_page_sections_and_chinese_split():
    detail = parse_lot_detail(page("lot_detail.html"))
    assert "中文说明" in detail["description"]
    assert "中文说明" not in detail["description_en"]
    assert detail["medium"] == "oil on canvas" and detail["year_created"] == 2015
    assert detail["provenance"] == "Private collection, Hong Kong\nAcquired from the above"
    assert detail["literature"] == "Catalogue, 2016, p. 12"
    assert detail["exhibited"] is None


def test_result_box_and_merge_clears_hidden_flag():
    response = page("lot_detail.html")
    assert parse_result_box(response) == {"label": "Lot Sold", "amount": 409600, "currency": "HKD"}
    lot = AuctionLot(lot_id="x", lot_status="hidden", data_quality_flags="result_not_public;other")
    merge_detail(lot, response)
    assert (lot.sold_price, lot.lot_status, lot.is_sold) == (409600, "sold", True)
    assert lot.data_quality_flags == "other" and lot.parse_quality == "detail"


def test_legacy_lot_description_written_as_paragraphs():
    url = "https://www.sothebys.com/en/auctions/ecatalogue/2015/ming-furniture-the-dr-s-y-yip-collection-hk0624/lot.1.html"
    lot = parse_legacy_lot(page("legacy_lot_paragraphs.html", url), {}, "t")
    assert lot.description.startswith("The top of standard mitre")
    assert "single-board, huamu floating panel" in lot.description  # <i> text glued back
    assert "undercoating is almost completely intact" in lot.description
    assert "Hong Kong Museum of Art" not in lot.description  # Exhibited list is not description
    assert lot.description_en == lot.description
    assert "Hong Kong Museum of Art" in lot.exhibited
    assert "Grace Wu Bruce" in lot.literature


def test_real_ming_furniture_page_hk0624_lot32():
    """Saved live page: empty <ul class="LotPage-lotDetails"> + <div class="LotPage-lotDescription">."""
    url = "https://www.sothebys.com/en/auctions/ecatalogue/2015/ming-furniture-the-dr-s-y-yip-collection-hk0624/lot.32.html"
    lot = parse_legacy_lot(page("legacy_lot_hk0624_32.html", url), {}, "t")
    assert lot.description.startswith("The top plank of the box is curved")
    assert lot.description.endswith("travelling pillows.")
    assert "Grace Wu Bruce" in lot.literature
    assert lot.exhibited.startswith("Hong Kong, 2007, Art Museum")
    assert lot.catalogue_note.startswith("This classical design")
    assert (lot.estimate_low, lot.estimate_currency) == (60000, "HKD")
    assert lot.provenance is None  # this lot has no Provenance section


def test_two_letter_sale_code_gives_lot_id_and_image():
    url = "https://www.sothebys.com/en/auctions/ecatalogue/2015/ming-furniture-the-dr-s-y-yip-collection-hk0624/lot.32.html"
    lot = parse_legacy_lot(page("legacy_lot_hk0624_32.html", url), {}, "t")
    assert (lot.sale_number, lot.auction_id, lot.lot_id) == ("HK0624", "HK0624", "HK0624-lot32")
    assert lot.image_url.startswith("https://sothebys-com.brightspotcdn.com/")
    assert "063hk0624-8gp5m.jpg" in lot.image_url and " " not in lot.image_url


def test_sale_code_from_url_when_page_has_none():
    url = "https://www.sothebys.com/en/auctions/ecatalogue/2015/crossroads-wei-dong-hk0614/lot.12.html"
    lot = parse_legacy_lot(page("legacy_lot.html", url), {}, "t")
    assert lot.lot_id == "HK0614-lot12"