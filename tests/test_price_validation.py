"""Every rule a sold price must pass (utils/price_validation.py)."""

import pytest

from utils.price_validation import as_bool, as_int, check_sold_price, parse_price_text

GOOD = dict(lot_status="sold", is_sold="True", is_closed="True", reserve_met="True", sold_price="1890",
            sold_currency="EUR", estimate_low="1500", estimate_high="2000", estimate_currency="EUR")


def rules(**changes):
    check = check_sold_price({**GOOD, **changes})
    return set(check.errors), set(check.warnings)


def test_a_normal_sale_passes_with_no_warnings():
    assert rules() == (set(), set())


def test_rows_without_a_price_or_sale_claim_pass():
    assert rules(lot_status="hidden", is_sold="", sold_price="", sold_currency="") == (set(), set())
    assert rules(lot_status="unsold", is_sold="False", sold_price="", sold_currency="") == (set(), set())


@pytest.mark.parametrize("changes, error", [
    (dict(sold_price=""), "sold_without_price"),
    (dict(sold_price="", lot_status="hidden", is_sold=""), "currency_without_price"),
    (dict(sold_price="0"), "not_positive"),
    (dict(sold_price="-5"), "not_positive"),
    (dict(sold_price="12.5"), "not_a_whole_number"),
    (dict(sold_price="12,700"), "not_a_whole_number"),
    (dict(lot_status="hidden"), "price_but_status_hidden"),
    (dict(lot_status="unsold", is_sold="False"), "price_but_status_unsold"),
    (dict(is_sold=""), "price_but_is_sold_not_true"),
    (dict(is_closed="False"), "sold_before_auction_closed"),
    (dict(lot_status="withdrawn"), "withdrawn_lot_with_price"),
    (dict(sold_currency=""), "currency_missing"),
    (dict(sold_currency="eur"), "currency_not_iso"),
    (dict(sold_currency="€"), "currency_not_iso"),
    (dict(sold_currency="USD"), "currency_differs_from_estimate"),
    (dict(sold_price="20"), "implausibly_low_vs_estimate"),          # 20 / 1500 < 2 %
    (dict(sold_price="400000"), "implausibly_high_vs_estimate"),     # 267x the low estimate
])
def test_each_error_rule(changes, error):
    errors, _ = rules(**changes)
    assert error in errors


@pytest.mark.parametrize("changes, warning", [
    (dict(sold_price="600"), "far_below_estimate"),
    (dict(sold_price="40000"), "far_above_estimate"),
    (dict(reserve_met="False"), "sold_but_reserve_not_met"),
    (dict(estimate_low="", estimate_high=""), "no_estimate_to_compare"),
])
def test_each_warning_rule_and_no_error(changes, warning):
    errors, warnings = rules(**changes)
    assert warning in warnings and not errors


def test_python_values_work_as_well_as_csv_text():
    row = dict(GOOD, is_sold=True, is_closed=True, reserve_met=True, sold_price=1890, estimate_low=1500, estimate_high=2000)
    assert check_sold_price(row).ok and check_sold_price(row).flags() == []


def test_flags_and_summary():
    check = check_sold_price({**GOOD, "sold_currency": "USD", "reserve_met": "False"})
    assert check.flags() == ["price_error_currency_differs_from_estimate", "price_warn_sold_but_reserve_not_met"]
    assert check.summary().startswith("error:")


@pytest.mark.parametrize("text, expected", [
    ("12,700 EUR", (12700, "EUR")), ("EUR 12,700", (12700, "EUR")), ("1,234,000 HKD", (1234000, "HKD")),
    ("950 GBP", (950, "GBP")), ("12,700.00 USD", (12700, "USD")), ("  409,600 HKD ", (409600, "HKD")),
    ("12.700 EUR", None), ("1,234.56 USD", None), ("12,70 EUR", None), ("12700", None), ("EUR 12,700 EUR", None),
    ("€12,700", None), ("12,700 eur", None), ("", None), (None, None), ("123456 EUR", None),
])
def test_price_text_is_read_strictly(text, expected):
    assert parse_price_text(text) == expected


def test_as_int_and_as_bool():
    assert as_int("") is None and as_int("12") == 12 and as_int("12.0") == 12 and as_int(7.0) == 7
    with pytest.raises(ValueError):
        as_int("1,200")
    assert as_bool("True") is True and as_bool("false") is False and as_bool("") is None


def test_no_reserve_lots_do_not_warn_about_the_reserve():
    assert rules(reserve_met="False", data_quality_flags="no_reserve") == (set(), set())
