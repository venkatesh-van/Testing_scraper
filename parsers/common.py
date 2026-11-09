"""Tiny helpers shared by every parser."""

from datetime import datetime, timezone


def to_int(value):
    """'150,000' -> 150000, 0 -> 0, None / '' / junk -> None (zero is NOT missing)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return None


def clean_text(value):
    """Strip a string; empty becomes None."""
    if value is None:
        return None
    return str(value).strip() or None


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
