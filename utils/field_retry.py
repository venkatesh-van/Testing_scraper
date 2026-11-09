"""Fetch a lot page again when some text sections came back empty.

A page can load with parts missing (slow server, partial render). Each retry keeps every
value found on earlier tries, so a retry can only add data, never lose it. After
`field_retries` tries, the blanks left are taken as 'not on page' (the lot has no such section).
"""

RETRY_FIELDS = ("description", "provenance", "literature", "exhibited", "catalogue_note")
DEFAULT_FIELD_RETRIES = 2


def _blank(value):
    return value is None or str(value).strip() == ""


def blank_fields(lot, fields):
    return [name for name in fields if _blank(getattr(lot, name, None))]


def snapshot(lot, fields):
    """Values found so far, carried to the next try."""
    return {name: getattr(lot, name) for name in fields if not _blank(getattr(lot, name, None))}


def restore(lot, saved):
    """Put back values an earlier try found but this try did not."""
    for name, value in (saved or {}).items():
        if _blank(getattr(lot, name, None)):
            setattr(lot, name, value)


def field_retry_request(request, tries, saved, first_missing):
    meta = dict(request.meta)
    meta.update({"field_tries": tries + 1, "field_saved": saved, "field_first_missing": first_missing})
    return request.replace(dont_filter=True, meta=meta)