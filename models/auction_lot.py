"""The one row schema shared by recent and historical data.

Field order here is the CSV column order. One lot = one row; `lot_id` is the key.
"""

from dataclasses import dataclass, fields
from typing import Optional

LOT_STATUSES = ("sold", "unsold", "withdrawn", "upcoming", "hidden", "unknown")


def merge_flags(existing, *new):
    """Join quality flags into one ';'-separated string without repeats."""
    flags = [flag for flag in (existing or "").split(";") if flag]
    for flag in new:
        if flag and flag not in flags:
            flags.append(flag)
    return ";".join(flags)


@dataclass
class AuctionLot:
    # --- auction
    auction_name: Optional[str] = None
    auction_detail: Optional[str] = None
    auction_category: Optional[str] = None
    auction_date: Optional[str] = None      # ISO YYYY-MM-DD (first day)
    auction_url: Optional[str] = None
    # --- the work
    lot_number: Optional[str] = None        # text: "12A" is valid
    artist: Optional[str] = None
    title: Optional[str] = None
    year_created: Optional[int] = None
    medium: Optional[str] = None
    dimensions: Optional[str] = None
    # --- estimate and result (None = not available; 0 is a real value)
    estimate_low: Optional[int] = None
    estimate_high: Optional[int] = None
    estimate_currency: Optional[str] = None
    is_closed: Optional[bool] = None
    reserve_met: Optional[bool] = None
    lot_status: Optional[str] = None        # one of LOT_STATUSES
    is_sold: Optional[bool] = None
    sold_price: Optional[int] = None        # final price incl. buyer's premium
    sold_currency: Optional[str] = None
    withdrawn_state: Optional[str] = None
    result_label: Optional[str] = None          # result text as shown on a public page, e.g. "Lot Sold"
    sold_price_source: Optional[str] = None     # where sold_price came from: graphql | lot_page | legacy_page
    # --- identity and links
    lot_id: Optional[str] = None
    auction_id: Optional[str] = None
    sale_number: Optional[str] = None
    lot_url: Optional[str] = None
    image_url: Optional[str] = None
    # --- text from the lot page
    description: Optional[str] = None
    description_en: Optional[str] = None
    provenance: Optional[str] = None
    literature: Optional[str] = None
    exhibited: Optional[str] = None
    catalogue_note: Optional[str] = None
    # --- lineage
    scraped_at: Optional[str] = None
    source_version: Optional[str] = None
    # detail = lot page read | good = list card complete but lot page NOT read (no description etc.)
    # partial = list card incomplete | legacy = old /ecatalogue/ page
    parse_quality: Optional[str] = None
    data_quality_flags: Optional[str] = None

    def add_flag(self, *flags):
        self.data_quality_flags = merge_flags(self.data_quality_flags, *flags)


FIELDS = [field.name for field in fields(AuctionLot)]
