"""Data completeness table printed in the terminal at the end of a run.

Used by recent_auctions / historical_auctions (on the csv they just wrote, after validation)
and by repair_details (on the csv it repaired).
"""

import csv
from pathlib import Path

REPORT_COLUMNS = ("description", "description_en", "provenance", "literature", "exhibited",
                  "catalogue_note", "dimensions", "medium", "year_created",
                  "estimate_low", "estimate_high", "sold_price")


def _blank(value):
    return value is None or str(value).strip() == ""


def completeness_report(rows, columns, absent=None):
    """Lines for the terminal: how full each column is.

    absent: {column: n} lots whose page was read (and retried) this run and has no such
    section, i.e. blanks that are correct. 'complete %' counts them as done.
    """
    absent = absent or {}
    total = len(rows) or 1
    width = max(len(name) for name in columns) + 2
    rule = "-" * (width + 48)
    lines = [f"{'column':<{width}}{'filled':>8}{'%':>8}{'empty':>7}{'not on page':>13}{'complete %':>12}", rule]
    sum_filled = sum_done = 0
    for name in columns:
        filled = sum(1 for row in rows if not _blank(row.get(name)))
        missing = len(rows) - filled
        not_on_page = min(absent.get(name, 0), missing)
        done = filled + not_on_page
        sum_filled += filled
        sum_done += done
        lines.append(f"{name:<{width}}{filled:>8}{100 * filled / total:>7.1f}%{missing:>7}"
                     f"{not_on_page:>13}{100 * done / total:>11.1f}%")
    cells = total * len(columns)
    lines += [rule, f"{'ALL':<{width}}{sum_filled:>8}{100 * sum_filled / cells:>7.1f}%"
                    f"{cells - sum_filled:>7}{sum_done - sum_filled:>13}{100 * sum_done / cells:>11.1f}%"]
    return lines


def print_completeness(title, rows, columns=REPORT_COLUMNS, absent=None, header=None):
    if header is not None:
        columns = [name for name in columns if name in header]
    print()
    print(f"=== DATA COMPLETENESS: {title} ({len(rows)} rows) ===")
    for line in completeness_report(rows, columns, absent):
        print(line)
    print("filled      = cells with a value now")
    print("not on page = blank, but the lot page was read (and retried) this run and has no such section")
    print("complete %  = filled + not on page")
    print()


def print_csv_completeness(path, absent=None, columns=REPORT_COLUMNS):
    path = Path(path) if path else None
    if not path or not path.exists():
        return
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        header = reader.fieldnames or []
    print_completeness(path.name, rows, columns, absent, header)