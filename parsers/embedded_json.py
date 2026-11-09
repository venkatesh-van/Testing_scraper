"""The JSON a lot page embeds (__NEXT_DATA__, ld+json): a fallback when the visible text is empty.

Some lot pages are built by script: the description is only in this JSON. The object that
mentions THIS lot's slug wins, so other lots on the page are never used.
"""

import json
import re

from parsers.lot_sections import SECTION_FIELDS
from parsers.page_text import html_to_text

# Keys in the page's embedded JSON (__NEXT_DATA__, ld+json) -> column. Compared lower case,
# without '_' or '-'. Used when the visible HTML has no text (pages built by script).
JSON_KEYS = {"description": "description", "lotdescription": "description",
             "provenance": "provenance", "literature": "literature", "bibliography": "literature",
             "exhibited": "exhibited", "exhibition": "exhibited", "exhibitions": "exhibited",
             "exhibitionhistory": "exhibited", "cataloguenote": "catalogue_note",
             "catalognote": "catalogue_note", "essay": "catalogue_note", "lotessay": "catalogue_note"}

JSON_COLUMNS = ("description",) + SECTION_FIELDS


# ---------------------------------------------------------------- embedded JSON
def embedded_json(response):
    """Every JSON blob the page embeds: __NEXT_DATA__ and ld+json scripts."""
    blobs = []
    for raw in response.css('script#__NEXT_DATA__::text, script[type="application/ld+json"]::text').getall():
        try:
            blobs.append(json.loads(raw))
        except (ValueError, TypeError):
            continue
    return blobs


def _json_text(value):
    """A JSON value as plain text: a string, {'html': ...}-style rich text, or a list of either."""
    if isinstance(value, str):
        return html_to_text(value)
    if isinstance(value, dict):
        for key in ("html", "text", "value", "content", "body"):
            if isinstance(value.get(key), str):
                return html_to_text(value[key])
        return ""
    if isinstance(value, list):
        return "\n".join(part for part in (_json_text(item) for item in value) if part)
    return ""


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def lot_text_from_json(blobs, lot_slug=None):
    """{column: text} from the JSON object that best looks like THIS lot.

    Score: mentions this lot's slug, then how many of the wanted keys it has, then length.
    An object with only 'description' and no slug is skipped when another object has more,
    so the site's own SEO text does not win over the lot.
    """
    best, best_score = {}, None
    for blob in blobs:
        for node in _walk(blob):
            hits = {}
            for key, value in node.items():
                column = JSON_KEYS.get(re.sub(r"[_\-]", "", str(key)).lower())
                if column and column not in hits:
                    text = _json_text(value)
                    if len(text) >= 3:
                        hits[column] = text
            if not hits:
                continue
            mentions = bool(lot_slug) and f'"{lot_slug}"' in json.dumps(node, ensure_ascii=False)
            score = (mentions, len(hits), sum(len(text) for text in hits.values()))
            if best_score is None or score > best_score:
                best, best_score = hits, score
    return best


def lot_slug_of(url):
    return (url or "").rstrip("/").rsplit("/", 1)[-1] or None
