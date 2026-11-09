"""Read a lot's own page: the entry point used by the spiders.

    analyse_detail(response) -> DetailReport   what the page gave, what is blank and why
    merge_detail(lot, response, report)        put it on an AuctionLot (never erases a value)

The work is done by small modules, each with one job:
    parsers/page_text.py      HTML -> clean lines of text
    parsers/lot_sections.py   Description / Provenance / Literature / ... sections
    parsers/lot_facts.py      dimensions, medium, year from the description
    parsers/embedded_json.py  the page's own JSON, when the visible text is empty
Names from those modules are re-exported here, so older imports keep working.
"""

from dataclasses import dataclass, field

from parsers.embedded_json import embedded_json, lot_slug_of, lot_text_from_json
from parsers.lot_facts import EVIDENCE_SIZE, MEDIUM_WORDS, extract_facts, find_size, infer_medium
from parsers.lot_sections import HEADINGS, SECTION_FIELDS, split_sections, split_subsections
from parsers.page_text import english_part, heading_key, html_to_text, visible_lines
from utils.price_validation import parse_price_text

GAP_FIELDS = ("description", "dimensions", "medium")   # a lot page normally gives these


@dataclass
class DetailReport:
    """What one lot page gave, and what is still blank (and why)."""
    detail: dict                                     # column -> value (None when blank)
    complete: bool                                   # False = page looks like a shell / partial page
    flags: list = field(default_factory=list)        # quality flags earned by fallbacks / failed parses
    gaps: dict = field(default_factory=dict)         # blank column -> "incomplete" | "parse_failed" | "absent"


# ---------------------------------------------------------------- the report
def analyse_detail(response):
    """Read a lot page, try the fallbacks, and say exactly what is missing and why.

    Fallbacks only look at THIS lot's own text (never the 'You May Also Like' lots):
      * description: og:description, then the page's Description section, then the page's
        embedded JSON (flag `description_from_page_json`), then the meta description
        (flag `description_partial`: it may be a shortened text)
      * provenance / literature / exhibited / catalogue note: the page's sections, then the
        embedded JSON (`<column>_from_page_json`), then a sub-heading such as
        'RELATED LITERATURE' inside the catalogue note or description (`<column>_from_note`,
        `<column>_from_description`)
      * dimensions / medium: the description, then the page's Description section, then (size)
        a size given in inches only (`dimensions_inches_only`), then (medium) a wider search
    A blank is "parse_failed" when evidence of the data is on the page, "absent" when not.
    """
    lines = visible_lines(response)
    sections = split_sections(lines)
    lowered = {heading_key(line) for line in lines}
    og = (response.css('meta[property="og:description"]::attr(content)').get() or "").strip()
    page_json = lot_text_from_json(embedded_json(response), lot_slug_of(response.url))
    complete = (bool(og) or "lot details" in lowered or any(heading in lowered for heading in HEADINGS)
                or "description" in page_json)
    flags = []

    description = html_to_text(og) or sections.get("description", "")
    if not description and page_json.get("description"):
        description = page_json["description"]
        flags.append("description_from_page_json")
    if not description:
        meta = response.css('meta[name="description"]::attr(content), '
                            'meta[name="twitter:description"]::attr(content)').get()
        description = html_to_text(meta)
        if description:
            flags.append("description_partial")
    description_en = english_part(description)

    texts = {name: sections.get(name) or None for name in SECTION_FIELDS}
    for name in SECTION_FIELDS:
        if texts[name] is None and page_json.get(name):
            texts[name] = page_json[name]
            flags.append(f"{name}_from_page_json")
    for source, label in ((texts["catalogue_note"], "note"), (description_en, "description")):
        for name, text in split_subsections(source).items():
            if texts.get(name) is None:
                texts[name] = text
                flags.append(f"{name}_from_{label}")

    facts = extract_facts(description_en)
    block = english_part(sections.get("description", ""))
    if block and (facts["dimensions"] is None or facts["medium"] is None):
        alt = extract_facts(block)
        for name in ("dimensions", "medium"):
            if facts[name] is None and alt[name]:
                facts[name] = alt[name]
                flags.append(f"{name}_from_page_text")
    text = description_en or block
    if facts["dimensions"] is None:
        line, unit = find_size(text)
        if unit == "inches":
            facts["dimensions"] = line
            flags.append("dimensions_inches_only")
    if facts["medium"] is None and facts["dimensions"]:
        inferred = infer_medium(text)
        if inferred:
            facts["medium"] = inferred
            flags.append("medium_inferred")

    detail = {
        "description": description or None,
        "description_en": description_en or None,
        **texts,
        **facts,
    }

    gaps = {}
    for name in GAP_FIELDS:
        if detail[name] is not None:
            continue
        if not complete:
            gaps[name] = "incomplete"
        elif name == "dimensions" and EVIDENCE_SIZE.search(text):
            gaps[name] = "parse_failed"
        elif name == "medium" and any(MEDIUM_WORDS.search(line) and len(line) <= 100
                                      for line in text.split("\n")[1:]):
            gaps[name] = "parse_failed"
        else:
            gaps[name] = "absent"
    for name in SECTION_FIELDS:                      # heading is on the page but its text came out empty
        if detail[name] is None and name in sections:
            gaps[name] = "parse_failed"
    for name, kind in gaps.items():
        if kind == "parse_failed":
            flags.append(f"{name}_parse_failed")
    return DetailReport(detail=detail, complete=complete, flags=flags, gaps=gaps)


def parse_lot_detail(response):
    """All text columns a lot page can fill, as a plain dict."""
    return analyse_detail(response).detail


def parse_result_box(response):
    """The result box, e.g. ['Lot Sold', '409,600 HKD']; empty when not public."""
    texts = response.css('[data-testid="lotBidAmount"]')[:1].css("p::text").getall() + ["", ""]
    label, amount = texts[0].strip(), texts[1].strip()
    parsed = parse_price_text(amount)          # strict: '12.700 EUR' or '1,234.56' give nothing
    return {
        "label": label or None,
        "amount": parsed[0] if parsed else None,
        "currency": parsed[1] if parsed else None,
    }


def merge_detail(lot, response, report=None):
    """Add the page's text (and a public result, if shown) to an existing lot.

    Only non-blank values are written, so a blank never erases data already on the lot.
    """
    report = report or analyse_detail(response)
    detail = report.detail
    for name, value in detail.items():
        if value not in (None, ""):
            setattr(lot, name, value)
    lot.add_flag(*report.flags)
    box = parse_result_box(response)
    if box["label"] == "Lot Sold" and box["amount"] is not None and lot.sold_price is None:
        lot.sold_price, lot.sold_currency = box["amount"], box["currency"]
        lot.is_sold, lot.lot_status = True, "sold"
        lot.sold_price_source = "lot_page"
        lot.result_label = box["label"]
        lot.data_quality_flags = ";".join(
            f for f in (lot.data_quality_flags or "").split(";") if f and f != "result_not_public")
    if detail["description"]:
        lot.parse_quality = "detail"
    return lot
