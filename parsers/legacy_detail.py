"""Read an older /ecatalogue/ lot page into the same shape analyse_detail() gives for new pages.

Used by:
  * spiders/historical_auctions.py  -> retry a legacy lot page that looks incomplete
  * spiders/repair_details.py       -> fill blank columns of historical rows

The report has the same four attributes the spiders already use:
  complete  True when the page has lot text (a Description or any other section)
  detail    {column: value} for every column the page filled
  flags     quality flags to add (none for legacy pages; parse_legacy_lot adds its own)
  gaps      {column: "absent"} for repair columns the page does not have
"""

from dataclasses import dataclass, field

from parsers.html_parser import parse_legacy_lot

# columns a legacy page can fill
LEGACY_DETAIL_FIELDS = (
    "description", "description_en", "provenance", "literature", "exhibited", "catalogue_note",
    "dimensions", "medium", "year_created",
    "estimate_low", "estimate_high", "estimate_currency", "sold_price", "sold_currency",
    "lot_id", "auction_id", "sale_number", "image_url",
)
SECTION_FIELDS = ("description", "provenance", "literature", "exhibited", "catalogue_note")


@dataclass
class LegacyReport:
    complete: bool
    detail: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)
    gaps: dict = field(default_factory=dict)


def is_legacy_url(url):
    """Older lot pages: /en/auctions/ecatalogue/<year>/<sale>/lot.<n>.html"""
    url = (url or "").lower()
    return "/ecatalogue/" in url and url.endswith(".html")


def legacy_report(response):
    lot = parse_legacy_lot(response, {}, "repair")
    detail = {}
    for name in LEGACY_DETAIL_FIELDS:
        value = getattr(lot, name, None)
        if value not in (None, ""):
            detail[name] = value if isinstance(value, str) else str(value)

    # A real lot page always has at least one text section. None at all = blocked / empty page.
    complete = any(name in detail for name in SECTION_FIELDS)
    gaps = {name: "absent" for name in LEGACY_DETAIL_FIELDS if name not in detail}
    return LegacyReport(complete=complete, detail=detail, gaps=gaps)