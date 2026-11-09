"""The named sections of a lot page: Description, Provenance, Literature, Exhibited, Catalogue Note.

split_sections()     the page's own headings          -> {column: text}
split_subsections()  sub-headings INSIDE a long text  -> {column: text}  ('RELATED LITERATURE')
"""

import re

from parsers.page_text import heading_key, join_fragments

# heading on the page (lower case, trailing ':' removed) -> column; None = a heading we only stop at
HEADINGS = {
    "description": "description",
    "provenance": "provenance",
    "literature": "literature",
    "related literature": "literature",
    "bibliography": "literature",
    "exhibited": "exhibited",
    "exhibition": "exhibited",
    "exhibitions": "exhibited",
    "exhibition history": "exhibited",
    "catalogue note": "catalogue_note",
    "essay": "catalogue_note",
    "lot essay": "catalogue_note",
    "condition report": None,
    "additional notices & disclaimers": None,
}

SECTION_FIELDS = ("provenance", "literature", "exhibited", "catalogue_note")

# A sub-heading INSIDE the catalogue note or description, e.g. "RELATED LITERATURE" (19 lots
# in the Al Thani sales keep their literature there, under no page heading of its own).
SUB_HEADING = re.compile(
    r"^\s*(?:(?:related|comparative|selected|further)\s+)?"
    r"(literature|bibliography|bibliographie|litt[ée]rature|exhibited|exhibitions?|expositions?|provenance)"
    r"\s*:?\s*$", re.I)

SUB_HEADING_COLUMN = {"literature": "literature", "bibliography": "literature", "bibliographie": "literature",
                      "littérature": "literature", "litterature": "literature",
                      "exhibited": "exhibited", "exhibition": "exhibited", "exhibitions": "exhibited",
                      "exposition": "exhibited", "expositions": "exhibited", "provenance": "provenance"}


def split_sections(lines):
    """Group page text under its headings (Provenance, Literature, ...)."""
    lowered = [heading_key(line) for line in lines]
    start = lowered.index("lot details") if "lot details" in lowered else 0
    sections, current = {}, None
    for line, key in zip(lines[start:], lowered[start:]):
        if key == "you may also like":
            break  # everything after is other lots
        if key in HEADINGS:
            current = HEADINGS[key]
            if current:
                sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return {
        name: "\n".join(text) if name == "description" else join_fragments(text)
        for name, text in sections.items()
    }


def split_subsections(text):
    """Text found under sub-headings such as 'RELATED LITERATURE' inside a longer text.

    Returns {column: text}. A sub-heading section runs until the next sub-heading or the end.
    """
    found, current = {}, None
    for line in (text or "").split("\n"):
        match = SUB_HEADING.match(line)
        if match:
            word = match.group(1).lower()
            current = SUB_HEADING_COLUMN.get(word) or SUB_HEADING_COLUMN.get(word.rstrip("s"))
            if current:
                found.setdefault(current, [])
            continue
        if current and line.strip():
            found[current].append(line.strip())
    return {name: join_fragments(lines) for name, lines in found.items() if lines}
