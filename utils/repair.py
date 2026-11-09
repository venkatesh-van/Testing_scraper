"""Fill blank detail columns of an EXISTING csv, without ever overwriting data.

Pure functions (no network): the repair_details spider uses them, and they are tested alone.
"""

import csv

from models.auction_lot import merge_flags
from parsers.lot_facts import facts_from_text

# Re-fetch a lot when any of these is blank. (medium is left out by default: 85% of lots have
# no medium, so asking for it would re-fetch almost every lot. Add it with -a only=...)
REPAIR_FIELDS = ("description", "description_en", "dimensions")
# Columns a lot page can fill.
FILLABLE = ("description", "description_en", "provenance", "literature", "exhibited",
            "catalogue_note", "medium", "dimensions", "year_created")
# Withdrawn lots are repaired too: 42 of the 46 withdrawn Al Thani lots have a description on
# their page. Use -a skip_withdrawn=1 to leave them out.
WITHDRAWN = "withdrawn"
# Set on a row once its page was read in full: the next run skips it (use -a recheck=1 to redo).
CHECKED_FLAG = "repair_checked"


def is_blank(value):
    return value is None or str(value).strip() == ""


def read_rows(path):
    """(header, rows) of a csv written by StoragePipeline (utf-8 with BOM)."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_rows(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def has_flag(row, flag):
    return flag in (row.get("data_quality_flags") or "").split(";")


def rows_needing_repair(rows, fields=REPAIR_FIELDS, recheck=False, skip_withdrawn=False):
    """Rows that have a lot_url and a blank in any of `fields` (withdrawn ones too, unless skip_withdrawn).

    Rows whose page was already read in full by an earlier repair run (flag repair_checked)
    are skipped unless `recheck`: fetching the same page again gives the same blanks.
    """
    return [row for row in rows
            if row.get("lot_url") and not (skip_withdrawn and row.get("lot_status") == WITHDRAWN)
            and (recheck or not has_flag(row, CHECKED_FLAG))
            and any(is_blank(row.get(name)) for name in fields)]


def offline_fill(row):
    """Fill blanks from text ALREADY in the row (no request). Returns the columns filled.

    * literature / exhibited / provenance from a sub-heading such as 'RELATED LITERATURE'
      inside the catalogue note or the description
    * dimensions from the description, including glued lines ('55mmFrench') and inch-only sizes
    """
    values, flags = facts_from_text(row.get("description_en") or row.get("description") or "",
                                    row.get("catalogue_note") or "")
    return fill_blanks(row, values, flags)


def fill_blanks(row, detail, flags=()):
    """Write `detail` values into the BLANK cells of `row`. Returns the columns filled.

    Never overwrites a cell that already has a value. Flags that describe the new values
    (for example dimensions_from_page_text) are added only for columns that were filled;
    `*_parse_failed` flags are always added, because they describe what is still blank.
    """
    filled = []
    for name in FILLABLE:
        new = detail.get(name)
        if is_blank(row.get(name)) and not is_blank(new):
            row[name] = str(new)
            filled.append(name)
    keep = [flag for flag in flags
            if flag.endswith("_parse_failed") or any(flag.startswith(name) for name in filled)]
    if keep:
        row["data_quality_flags"] = merge_flags(row.get("data_quality_flags"), *keep)
    if "description" in filled:
        row["parse_quality"] = "detail"
    return filled
