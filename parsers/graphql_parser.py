"""Turn the site's GraphQL lot-card JSON into AuctionLot rows. No network here."""

import re

from models.auction_lot import AuctionLot
from parsers.common import clean_text, to_int, utc_now_iso

NOT_WITHDRAWN = {"", "notaffected", "none"}


def find_lot_cards(value):
    """Yield every lot-card dict found anywhere in nested JSON."""
    if isinstance(value, dict):
        if "lotId" in value and "lotNumber" in value:
            yield value
        else:
            for child in value.values():
                yield from find_lot_cards(child)
    elif isinstance(value, list):
        for child in value:
            yield from find_lot_cards(child)


def parse_connection(payload):
    """Read one GraphQL page: its cards, totalCount, hasNextPage and errors."""
    connection = (((payload.get("data") or {}).get("auction")) or {}).get("lotCards") or {}
    return {
        "cards": list(find_lot_cards(connection)),
        "total": connection.get("totalCount"),
        "has_next": connection.get("hasNextPage"),
        "errors": payload.get("errors") or [],
    }


def derive_status(withdrawn_state, sold, is_closed):
    """Explicit lot status. A hidden result is NOT the same as unsold."""
    if withdrawn_state and withdrawn_state.strip().lower() not in NOT_WITHDRAWN:
        return "withdrawn"
    if sold.get("isSold") is True:
        return "sold"
    if sold.get("isSold") is False:
        return "unsold"
    if is_closed is False:
        return "upcoming"
    return "hidden"  # closed, but the public page gives no result


def first_large_image(card):
    for image in (card.get("media") or {}).get("images") or []:
        for rendition in image.get("renditions") or []:
            if rendition.get("imageSize") == "Large" and rendition.get("url"):
                return rendition["url"]
    return None


def split_artist_title(card):
    """'Artist | Title' with any spacing; decorative lots have no artist."""
    raw = card.get("title") or ""
    parts = re.split(r"\s*\|\s*", raw, maxsplit=1)
    if len(parts) == 2:
        return clean_text(parts[0]), clean_text(parts[1])
    return clean_text(card.get("creatorsDisplayTitle")), clean_text(raw)


def find_auction_id(value):
    """First 'auctionId' value found anywhere in nested JSON, or None.

    Fallback for auction pages whose __NEXT_DATA__ has no lot cards: we can still
    ask GraphQL for the lots if the page contains the auction id somewhere.
    """
    if isinstance(value, dict):
        found = value.get("auctionId")
        if isinstance(found, str) and found:
            return found
        children = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return None
    for child in children:
        found = find_auction_id(child)
        if found:
            return found
    return None


def parse_card(card, auction_info, source_version):
    """Map one lot card to an AuctionLot. Missing pieces stay None and get a flag."""
    auction = card.get("auction") or {}
    slug = auction.get("slug") or {}
    bid = card.get("bidState") or {}
    sold = bid.get("sold") or {}
    estimate = card.get("estimateV2") or {}
    final = ((sold.get("premiums") or {}).get("finalPrice")) or {}
    withdrawn = (card.get("withdrawnState") or {}).get("state")
    is_closed = bid.get("isClosed")

    artist, title = split_artist_title(card)
    lot_number = (card.get("lotNumber") or {}).get("lotDisplayNumber")
    lot_slug = (card.get("slug") or {}).get("lotSlug")
    lot_url = None
    if slug.get("year") and slug.get("name") and lot_slug:
        lot_url = f"https://www.sothebys.com/en/buy/auction/{slug['year']}/{slug['name']}/{lot_slug}"

    status = derive_status(withdrawn, sold, is_closed)
    lot = AuctionLot(
        auction_name=auction_info.get("auction_name"),
        auction_detail=auction_info.get("auction_detail"),
        auction_category=auction_info.get("auction_category"),
        auction_date=auction_info.get("auction_date"),
        auction_url=auction_info.get("auction_url"),
        lot_number=str(lot_number) if lot_number is not None else None,
        artist=artist,
        title=title,
        estimate_low=to_int((estimate.get("lowEstimate") or {}).get("amount")),
        estimate_high=to_int((estimate.get("highEstimate") or {}).get("amount")),
        estimate_currency=auction.get("currency"),
        is_closed=is_closed,
        reserve_met=bid.get("reserveMet"),
        lot_status=status,
        is_sold=sold.get("isSold"),
        sold_price=to_int(final.get("amount")),
        sold_currency=final.get("currency"),
        sold_price_source="graphql" if final.get("amount") is not None else None,
        withdrawn_state=withdrawn,
        lot_id=card.get("lotId"),
        auction_id=auction.get("auctionId"),
        sale_number=auction.get("sapSaleNumber"),
        lot_url=lot_url,
        image_url=first_large_image(card),
        scraped_at=utc_now_iso(),
        source_version=source_version,
        parse_quality="good" if (lot_number is not None and card.get("lotId") and title) else "partial",
    )
    if status == "hidden":
        lot.add_flag("result_not_public")
    if estimate.get("__typename") == "EstimateUponRequest":
        lot.add_flag("estimate_on_request")
    elif lot.estimate_low is None and lot.estimate_high is None:
        lot.add_flag("estimate_missing")
    if lot_url is None:
        lot.add_flag("lot_url_missing")
    return lot
