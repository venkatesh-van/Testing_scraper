"""Where is the data blank, and is it expected?

    python gap_report.py data/processed/recent_auctions_recent.csv
    python gap_report.py data/processed/recent_auctions_recent.csv description dimensions

For each column: how many rows are blank, split into withdrawn lots (little data expected)
and other lots (a blank here is worth a look). Then lists the first lots to open by hand.
"""

import sys
from collections import Counter

from utils.repair import is_blank, read_rows

# parse_quality says how far the row got. NOTE: "good" does NOT mean the details are there.
MEANING = {
    "detail": "lot page read: description and the other page fields are filled",
    "good": "list card only (lot number, id, title complete); the lot page was NOT read, "
            "so description, dimensions, provenance, literature ... are blank",
    "partial": "list card only, and the card itself is missing lot number, id or title",
    "legacy": "older /ecatalogue/ page (2015-style); layout unverified",
}


def column_table(rows, columns):
    """[(column, blank, blank_withdrawn, blank_other, fill_percent)]"""
    table = []
    for name in columns:
        empty = [r for r in rows if is_blank(r.get(name))]
        withdrawn = sum(r.get("lot_status") == "withdrawn" for r in empty)
        table.append((name, len(empty), withdrawn, len(empty) - withdrawn, 100 * (1 - len(empty) / len(rows))))
    return table


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    path, only = argv[0], argv[1:]
    header, rows = read_rows(path)
    if not rows:
        print(f"{path}: no rows")
        return 0

    print(f"{path}: {len(rows)} rows, {sum(r.get('lot_status') == 'withdrawn' for r in rows)} withdrawn\n")
    print(f"{'column':22s}{'blank':>7s}{'withdrawn':>11s}{'other':>7s}{'fill %':>8s}")
    for name, empty, withdrawn, other, fill in column_table(rows, only or header):
        print(f"{name:22s}{empty:7d}{withdrawn:11d}{other:7d}{fill:7.1f}%")

    print("\nparse_quality (how far each row got):")
    for quality, count in Counter(r.get("parse_quality") or "(blank)" for r in rows).most_common():
        print(f"  {quality:8s}{count:6d}  {MEANING.get(quality, '')}")
    needs_page = [r for r in rows if r.get("parse_quality") in ("good", "partial")]
    if needs_page:
        print(f"  -> {len(needs_page)} rows never had their lot page read. Fill them with:")
        print(f"     scrapy crawl repair_details -a source={path} -a retries=4")

    flags = Counter(flag for r in rows for flag in (r.get("data_quality_flags") or "").split(";") if flag)
    print("\nquality flags:", dict(flags) or "none")

    for name in (only or ["description", "dimensions"]):
        todo = [r for r in rows if is_blank(r.get(name))]
        print(f"\nFirst lots with a blank '{name}' ({len(todo)} in total): open these by hand")
        for r in todo[:8]:
            status = "withdrawn" if r.get("lot_status") == "withdrawn" else ""
            print(f"  lot {r.get('lot_number', ''):>5s}  {r.get('title', '')[:40]:40s}  "
                  f"{r.get('parse_quality', ''):7s} {status:9s} {r.get('lot_url', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
