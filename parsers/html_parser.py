"""HTML pages: the results list, auction dates, and the older /ecatalogue/ lot pages."""

import re
from datetime import date, datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.parse import parse_qs, urlparse
from urllib.parse import urlparse

from models.auction_lot import AuctionLot
from parsers.common import clean_text, to_int, utc_now_iso
from parsers.lot_detail_parser import extract_facts, split_sections, visible_lines

# "29 September–5 October 2026", "9 October 2026", "29–30 September 2026"
DATE_RANGE = re.compile(
    r"(\d{1,2})\s*([A-Za-z]+)?\s*(?:[–—-]\s*(\d{1,2})\s*([A-Za-z]+))?\s+(\d{4})")
LEGACY_LOT_NUMBER = re.compile(r"lot\.(\d+[A-Za-z]?)\.html", re.I)
LEGACY_SALE_NUMBER = re.compile(r"-([a-z]{1,3}\d{4,5})/", re.I)  # ...-n09375/, ...-hk0614/
ESTIMATE = re.compile(r"Estimate[:\s]*([\d,]+)\s*[-\u2013]\s*([\d,]+)\s*([A-Z]{3})?")
SOLD = re.compile(r"(?:Lot Sold|Sold for|Price Reali[sz]ed)[:\s]*([\d,]+)\s*([A-Z]{3})?", re.I)

# Link text that means "go to the next page of the results list"
NEXT_LABELS = ("next", "load more", "show more", "more results")


def _month(name):
    for fmt in ("%B", "%b"):
        try:
            return datetime.strptime(name, fmt).month
        except (ValueError, TypeError):
            pass
    return None


def parse_auction_dates(text):
    """(first_day, last_day) as ISO strings, or (None, None) when unreadable."""
    for match in DATE_RANGE.finditer(text or ""):
        day1, month1, day2, month2, year = match.groups()
        end_month = _month(month2) if month2 else _month(month1)
        start_month = _month(month1) if month1 else end_month
        if not start_month or not end_month:
            continue
        year = int(year)
        end_day = int(day2) if day2 else int(day1)
        start_year = year - 1 if start_month > end_month else year  # 30 Dec - 2 Jan
        try:
            return (date(start_year, start_month, int(day1)).isoformat(),
                    date(year, end_month, end_day).isoformat())
        except ValueError:
            continue
    return None, None


def parse_auction_cards(response):
    """Results page -> one dict per auction card."""
    auctions = []
    for card in response.css("div.Card"):
        href = card.css("a::attr(href)").get()
        if not href:
            continue
        detail = clean_text(card.css("div.Card-details::text").get())
        auctions.append({
            "auction_name": clean_text(card.css("div.Card-title::text").get()),
            "auction_detail": detail,
            "auction_category": clean_text(card.css("div.Card-category::text").get()),
            "auction_date": parse_auction_dates(detail)[0],
            "auction_url": response.urljoin(href),
        })
    return auctions


def results_next_page(response):
    """URL of the next RESULTS page (the list of auctions), or None.

    The lots inside one auction are paged through GraphQL, but the list of
    auctions can be paged too. If the site does this with JavaScript only
    ("Load more" button with no href), this returns None and you must find
    the underlying API call in the browser's Network tab instead.
    """
    href = response.css('a[rel="next"]::attr(href), link[rel="next"]::attr(href)').get()
    if not href:
        for link in response.css("a"):
            label = " ".join(link.css("::text").getall()).strip().lower()
            label = label or (link.attrib.get("aria-label") or "").lower()
            if label in NEXT_LABELS:
                href = link.attrib.get("href")
                break
    if not href or href == "#" or href.startswith("javascript"):
        return None
    url = response.urljoin(href)
    return None if url == response.url else url


def find_filter_values(response, param="f2"):
    """Every value of a filter parameter (like f2) that the results page offers.

    Returns {value: label}. Looks in links (?f2=...), inputs and <select> options.
    Returns {} if the filters are loaded by JavaScript and are not in the HTML.
    """
    found = {}
    for link in response.css("a"):
        href = link.attrib.get("href") or ""
        values = parse_qs(urlparse(href).query).get(param)
        if values:
            label = " ".join(link.css("::text").getall()).strip() or None
            found.setdefault(values[0], label)
    for value in response.css(
            f'input[name="{param}"]::attr(value), select[name="{param}"] option::attr(value)').getall():
        if value:
            found.setdefault(value, None)
    return found


def legacy_lot_links(response):
    """Unique absolute lot-page links on an older auction page, in page order."""
    hrefs = response.css('a[href*="/ecatalogue/"]::attr(href)').getall()
    return list(dict.fromkeys(response.urljoin(href) for href in hrefs))



def _with_query_param(url, name, value):
    """url with ?name=value set, keeping every other query parameter."""
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[name] = str(value)
    return urlunparse(parts._replace(query=urlencode(query)))


def legacy_next_page(response):
    """Next page of an older auction's lot list, or None.

    The real pager is a row of <button data-param-name="p" data-param-value="N"> (the page
    numbers plus a Next arrow). Take the smallest page number above the active one and
    return the same URL with ?p=N. Falls back to a plain "Next" / rel="next" link.
    """
    name, current, numbers = "p", None, set()
    for button in response.css("div.pagination button[data-param-value]"):
        value = (button.attrib.get("data-param-value") or "").strip()
        if not value.isdigit():
            continue
        name = button.attrib.get("data-param-name") or name
        if "active" in (button.attrib.get("class") or "").split():
            current = int(value)
        else:
            numbers.add(int(value))
    if numbers:
        if current is None:  # no active button: read the page from the URL, default 1
            from_url = dict(parse_qsl(urlparse(response.url).query)).get(name, "1")
            current = int(from_url) if from_url.isdigit() else 1
        later = [number for number in numbers if number > current]
        if later:
            return _with_query_param(response.url, name, min(later))
        return None  # the pager exists and there is nothing after the current page

    href = response.xpath('//a[normalize-space()="Next"]/@href | //a[@rel="next"]/@href '
                          '| //link[@rel="next"]/@href').get()
    if href and href != "#" and not href.startswith("javascript"):
        return response.urljoin(href)
    return None


def legacy_prices(page_text):
    """Estimate and sold price from the page text (layout NOT verified on live pages)."""
    prices = {"estimate_low": None, "estimate_high": None, "estimate_currency": None,
              "sold_price": None, "sold_currency": None}
    estimate = ESTIMATE.search(page_text)
    if estimate:
        prices["estimate_low"] = to_int(estimate.group(1))
        prices["estimate_high"] = to_int(estimate.group(2))
        prices["estimate_currency"] = estimate.group(3)
    sold = SOLD.search(page_text)
    if sold:
        prices["sold_price"] = to_int(sold.group(1))
        prices["sold_currency"] = sold.group(2)
    return prices


def _join_lines(lines):
    """Inline tags (<i>, <em>) split one sentence over several text nodes; glue them back."""
    groups = []
    for line in lines:
        if not line:
            continue
        if groups and line[0] in ",.;:)":
            groups[-1].append(line)
        elif groups and line[0].islower():
            groups[-1].append(" " + line)
        else:
            groups.append([line])
    return "\n".join("".join(group) for group in groups)


def legacy_description(response, sections=None):
    """Text under the 'Description' heading.

    Paintings list it as a <ul> (one line per <li>); furniture and other
    objects write it as paragraphs. Try the list first, then the paragraphs.
    """
    items = response.xpath(
        '//*[self::h2 or self::h3][normalize-space()="Description"]/following::ul[1]/li')
    # keep the list only if it is inside the Description section, not a later one
    items = [li for li in items if li.xpath(
        'normalize-space(preceding::*[self::h2 or self::h3][1])').get() == "Description"]
    texts = (" ".join("".join(li.xpath(".//text()").getall()).split()) for li in items)
    from_list = "\n".join(text for text in texts if text)
    if from_list:
        return from_list
    # Ming furniture etc.: empty <ul class="LotPage-lotDetails"> then <div class="LotPage-lotDescription">
    block = response.xpath(
        '//*[self::h2 or self::h3][normalize-space()="Description"]'
        '/following-sibling::div[contains(@class, "LotPage-lotDescription")][1]')
    if block and block.xpath('normalize-space(preceding-sibling::*[self::h2 or self::h3][1])').get() == "Description":
        lines = [" ".join(t.split()) for t in block.xpath(".//text()").getall()]
        text = _join_lines([line for line in lines if line])
        if text:
            return text
    if sections is None:
        sections = split_sections(visible_lines(response))
    text = sections.get("description") or ""
    return _join_lines(text.split("\n")) if text else ""


def legacy_image(response):
    """Main lot image: the full-size picture of the first gallery slide."""
    candidates = [
        response.css(".VerticalNavGallerySlide img::attr(data-srcset)").get(),
        response.css(".VerticalNavGallerySlide img::attr(data-src)").get(),
        response.css('meta[property="og:image"]::attr(content)').get(),
        response.xpath('//main//img[contains(@data-src, "brightspotcdn")]/@data-src').get(),
    ]
    for value in candidates:
        url = (value or "").strip().split(" ")[0]   # srcset: "<url> 2880w" -> "<url>"
        if url.startswith("http"):
            return url
    return None


def parse_legacy_lot(response, auction_info, source_version):
    """Older /en/auctions/ecatalogue/... lot page -> AuctionLot (same schema)."""
    lines = visible_lines(response)
    page_text = " ".join(lines)
    artist = clean_text(" ".join(response.css("h1 ::text").getall()))
    page_title = clean_text(response.css("title::text").get())
    sections = split_sections(lines)
    description = legacy_description(response, sections)
    desc_lines = description.split("\n") if description else []
    # description list is: artist, title, signature, medium, size ...
    title = desc_lines[1] if len(desc_lines) > 1 and desc_lines[0] == artist else page_title

    number = LEGACY_LOT_NUMBER.search(response.url)
    sale = LEGACY_SALE_NUMBER.search(response.url + "/")
    lot_number = number.group(1) if number else None
    # the page states its sale id in a hidden input; the URL is the fallback
    page_sale = clean_text(response.css("input.sale_id::attr(value)").get())
    sale_number = (page_sale or (sale.group(1) if sale else "")).upper() or None

    prices = legacy_prices(page_text)
    lot = AuctionLot(
        auction_name=auction_info.get("auction_name"),
        auction_detail=auction_info.get("auction_detail"),
        auction_category=auction_info.get("auction_category"),
        auction_date=auction_info.get("auction_date"),
        auction_url=auction_info.get("auction_url"),
        lot_number=lot_number,
        artist=artist,
        title=title,
        is_closed="bidding is closed" in page_text.lower() or None,
        lot_status="sold" if prices["sold_price"] is not None else "unknown",
        is_sold=True if prices["sold_price"] is not None else None,
        lot_id=f"{sale_number}-lot{lot_number}" if sale_number and lot_number else response.url,
        auction_id=sale_number,
        sale_number=sale_number,
        lot_url=response.url,
        image_url=legacy_image(response),
        description=description or None,
        description_en=description or None,
        provenance=sections.get("provenance") or None,
        literature=sections.get("literature") or None,
        exhibited=sections.get("exhibited") or None,
        catalogue_note=sections.get("catalogue_note") or None,
        scraped_at=utc_now_iso(),
        source_version=source_version,
        parse_quality="legacy",
        **prices,
        **extract_facts(description),
    )
    lot.add_flag("legacy_layout_unverified")
    if lot.lot_status == "unknown":
        lot.add_flag("legacy_result_unknown")
    if lot.estimate_low is None:
        lot.add_flag("estimate_missing")
    return lot