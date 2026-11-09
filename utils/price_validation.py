"""Rules that a sold price must pass before it is trusted.

One function, `check_sold_price(row)`, used everywhere a price is written or checked:
  * pipelines/validation.py   (every crawled row)
  * validate_prices.py        (a full report on a csv)

It works on an AuctionLot, a dict of Python values, or a csv row (all text), so the same
rules run on fresh data and on files already on disk.

ERRORS mean the price is wrong or cannot be trusted: the row is flagged price_error_<rule>,
and validate_prices.py exits with code 1. WARNINGS mean "possible, but look at it by hand".
"""

import re
from dataclasses import dataclass, field

CURRENCY = re.compile(r"^[A-Z]{3}$")
# '12,700 EUR', 'EUR 12,700', '1,234,000 HKD', '950 GBP'. Not '12.700' (could be 12 thousand
# or 12 point 7) and not '1,234.56': an unclear amount is refused, never guessed.
PRICE_TEXT = re.compile(
    r"^(?:(?P<pre>[A-Z]{3})\s*)?(?P<amount>\d{1,3}(?:,\d{3})+|\d{1,4})(?:\.0{2})?\s*(?P<post>[A-Z]{3})?$")

# sold_price / estimate_low. sold_price includes the buyer's premium (about 20-27 %), so a
# normal sale lands around 1.2x-1.3x of the hammer. These bands are deliberately wide.
RATIO_ERROR_LOW = 0.02     # below 2 % of the low estimate: almost surely a parsing error
RATIO_ERROR_HIGH = 200     # 200x the low estimate: almost surely a parsing error (extra digits)
RATIO_WARN_LOW = 0.5       # sold far below the estimate: possible (no reserve), check by hand
RATIO_WARN_HIGH = 20       # sold far above the estimate: possible (bidding war), check by hand

@dataclass
class PriceCheck:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors

    def flags(self):
        """Quality flags for data_quality_flags: price_error_<rule> / price_warn_<rule>."""
        return [f"price_error_{name}" for name in self.errors] + [f"price_warn_{name}" for name in self.warnings]

    def summary(self):
        if self.errors:
            return "error: " + ", ".join(self.errors)
        if self.warnings:
            return "warning: " + ", ".join(self.warnings)
        return "ok"


def parse_price_text(text):
    """(amount, currency) from text such as '12,700 EUR'; None when the text is not clean."""
    text = re.sub(r"\s+", " ", (text or "").replace("\xa0", " ").replace("\u202f", " ")).strip()
    match = PRICE_TEXT.match(text)
    if not match:
        return None
    pre, post = match.group("pre"), match.group("post")
    if bool(pre) == bool(post):          # needs exactly one currency code
        return None
    return int(match.group("amount").replace(",", "")), pre or post


def _get(row, name):
    """A value from a dict, a csv row, an ItemAdapter (has .get) or an AuctionLot (attributes)."""
    getter = getattr(row, "get", None)
    return getter(name) if callable(getter) else getattr(row, name, None)


def as_int(value):
    """int, or None when blank. Raises ValueError for text that is not a whole number."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a price")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != int(value):
            raise ValueError(f"not a whole number: {value}")
        return int(value)
    text = str(value).strip()
    if re.fullmatch(r"-?\d+(\.0+)?", text):
        return int(float(text))
    raise ValueError(f"not a whole number: {value!r}")


def as_bool(value):
    """True / False / None. csv files hold 'True' / 'False' / ''."""
    if value is None or isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def check_sold_price(row):
    """All price rules for one row. Rows with no price and no 'sold' claim pass untouched."""
    check = PriceCheck()
    status = (_get(row, "lot_status") or "").strip().lower()
    is_sold = as_bool(_get(row, "is_sold"))
    is_closed = as_bool(_get(row, "is_closed"))
    reserve_met = as_bool(_get(row, "reserve_met"))
    currency = (_get(row, "sold_currency") or "").strip()
    estimate_currency = (_get(row, "estimate_currency") or "").strip()

    try:
        price = as_int(_get(row, "sold_price"))
    except ValueError:
        check.errors.append("not_a_whole_number")
        return check
    try:
        low = as_int(_get(row, "estimate_low"))
        high = as_int(_get(row, "estimate_high"))
    except ValueError:
        low = high = None
        check.warnings.append("estimate_not_a_number")

    claims_sold = status == "sold" or is_sold is True
    if price is None:
        if claims_sold:
            check.errors.append("sold_without_price")
        if currency:
            check.errors.append("currency_without_price")
        return check

    # --- a price is present: everything about it must agree
    if price <= 0:
        check.errors.append("not_positive")
    if status != "sold":
        check.errors.append(f"price_but_status_{status or 'blank'}")
    if is_sold is not True:
        check.errors.append("price_but_is_sold_not_true")
    if is_closed is False:
        check.errors.append("sold_before_auction_closed")
    if status == "withdrawn":
        check.errors.append("withdrawn_lot_with_price")
    if not currency:
        check.errors.append("currency_missing")
    elif not CURRENCY.match(currency):
        check.errors.append("currency_not_iso")
    elif estimate_currency and currency != estimate_currency:
        check.errors.append("currency_differs_from_estimate")   # a lot sells in the sale's currency

    if low and low > 0 and price > 0:
        ratio = price / low
        if ratio < RATIO_ERROR_LOW:
            check.errors.append("implausibly_low_vs_estimate")
        elif ratio > RATIO_ERROR_HIGH:
            check.errors.append("implausibly_high_vs_estimate")
        elif ratio < RATIO_WARN_LOW:
            check.warnings.append("far_below_estimate")
        elif ratio > RATIO_WARN_HIGH:
            check.warnings.append("far_above_estimate")
    elif low is None and high is None:
        check.warnings.append("no_estimate_to_compare")
    no_reserve = "no_reserve" in (_get(row, "data_quality_flags") or "").split(";")
    if reserve_met is False and status == "sold" and not no_reserve:     # 'No reserve' lots: normal
        check.warnings.append("sold_but_reserve_not_met")
    return check
