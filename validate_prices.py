"""Check every sold price in a csv. Exit code 1 when any price is wrong (so it can gate a release).

    python validate_prices.py                                   # the recent csv
    python validate_prices.py data/processed/historical_auctions_historical.csv
    python validate_prices.py --all                             # also print every warning row

Per row: every rule in utils/price_validation.py (status, is_sold, closed, currency, withdrawn,
price against the estimate, reserve). Across the file:
  * each price says where it came from (sold_price_source)
  * the result label agrees with the status ('Lot Sold' <-> sold, 'Lot Unsold' <-> unsold)
  * no lot_id appears twice

Writes <name>.price_check.csv: one line per row with an error or a warning, with the reason.
"""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from config.settings import PROCESSED_DIR
from utils.price_validation import check_sold_price
from utils.repair import read_rows

DEFAULT = PROCESSED_DIR / "recent_auctions_recent.csv"
REPORT_COLUMNS = ("level", "rule", "lot_id", "lot_number", "lot_status", "sold_price", "sold_currency",
                  "estimate_low", "estimate_high", "sold_price_source", "result_label", "lot_url")


def label_status(label):
    """'Lot Sold' -> 'sold', 'Lot Unsold' / 'Bought In' -> 'unsold', anything else -> None."""
    key = " ".join((label or "").split()).lower()
    if key in ("lot sold", "sold"):
        return "sold"
    if key in ("lot unsold", "unsold", "bought in", "lot bought in", "passed", "not sold", "lot not sold"):
        return "unsold"
    return None


def validate(rows):
    """[(level, rule, row)] for the whole file."""
    findings = []
    seen = Counter(row.get("lot_id") for row in rows)
    for row in rows:
        check = check_sold_price(row)
        findings += [("error", rule, row) for rule in check.errors]
        findings += [("warning", rule, row) for rule in check.warnings]
        price = (row.get("sold_price") or "").strip()
        status = (row.get("lot_status") or "").strip().lower()
        if price and not (row.get("sold_price_source") or "").strip():
            findings.append(("warning", "price_source_unknown", row))
        label = (row.get("result_label") or "").strip()
        if label and label_status(label) and label_status(label) != status:
            findings.append(("error", f"label_{label_status(label)}_but_status_{status or 'blank'}", row))
        if seen[row.get("lot_id")] > 1:
            findings.append(("error", "duplicate_lot_id", row))
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", nargs="?", default=str(DEFAULT))
    parser.add_argument("--all", action="store_true", help="print every warning row too")
    args = parser.parse_args(argv)
    path = Path(args.source)
    _, rows = read_rows(path)
    findings = validate(rows)

    statuses = Counter((row.get("lot_status") or "blank") for row in rows)
    priced = sum(1 for row in rows if (row.get("sold_price") or "").strip())
    sources = Counter((row.get("sold_price_source") or "none") for row in rows if (row.get("sold_price") or "").strip())
    errors = [f for f in findings if f[0] == "error"]
    warnings = [f for f in findings if f[0] == "warning"]
    bad_rows = {id(row) for _, _, row in errors}

    print(f"{path}: {len(rows)} rows")
    print(f"  lot_status: {dict(statuses)}")
    print(f"  rows with a sold price: {priced}   (sources: {dict(sources) or 'none'})")
    print(f"  price errors: {len(errors)} in {len(bad_rows)} rows   warnings: {len(warnings)}")
    if errors or warnings:
        print("  by rule:", dict(Counter(f"{level}:{rule}" for level, rule, _ in findings)))
    for level, rule, row in errors + (warnings if args.all else []):
        print(f"  {level.upper():7s} {rule:38s} lot {row.get('lot_number', ''):>5s}  "
              f"{row.get('sold_price') or '-':>10s} {row.get('sold_currency') or '':3s}  "
              f"est {row.get('estimate_low') or '?'}-{row.get('estimate_high') or '?'}  {row.get('lot_url', '')}")

    report = path.with_name(path.stem + ".price_check.csv")
    with open(report, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, REPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for level, rule, row in findings:
            writer.writerow({**row, "level": level, "rule": rule})
    print(f"  details: {report.name}")
    if errors:
        print("\nFAILED: fix or remove the prices above before using this file.")
        return 1
    print("\nOK: every sold price passed." if priced else "\nOK: no sold prices yet (nothing wrong either).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
