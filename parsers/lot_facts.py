"""Facts found inside the description text: dimensions, medium, year.

All heuristics live here, in one place, so they can be tuned and tested on their own.
"""

import re

from parsers.common import to_int
from parsers.lot_sections import split_subsections
from parsers.page_text import fact_lines

# "55mmFrench" is still a size: only a LOWER-case letter right after the unit rules it out.
DIMENSIONS = re.compile(r"\d\s*(?:cm|mm)(?![a-z])")

FRACTIONS = "½¼¾⅛⅜⅝⅞⅓⅔"      # ½ ¼ ¾ ⅛ ⅜ ⅝ ⅞ ⅓ ⅔

# A size in inches only ("4in wide", "2⅜in.", "12 by 10 in."), but not "1920 in Paris".
INCH_SIZE = re.compile(
    rf"[\d{FRACTIONS}]\s*(?:in\.|inch(?:es)?\b|in(?=\s*(?:$|[;,)]|wide|high|long|deep|diam)))", re.I | re.M)

SIGNATURE_LINE = re.compile(
    r"^(one |all )?(signed|inscribed|dated|stamped|bears|titled|numbered|executed)", re.I)

MEDIUM_WORDS = re.compile(
    r"\b(oil|acrylic|gouache|watercolou?r|ink|chalk|pencil|charcoal|bronze|marble|terracotta|"
    r"lithograph|etching|aquatint|engraving|screenprint|silkscreen|canvas|paper|panel|linen)\b", re.I)

YEAR_AFTER_VERB = re.compile(r"(?:Executed|Painted|Created|Cast|Conceived|Printed)[^.\n]*?(\d{4})")

YEAR_AFTER_DATED = re.compile(r"\bdated[^\n]*?(\d{4})")

# Evidence that a size is written on the page, even in units extract_facts() does not read.
EVIDENCE_SIZE = re.compile(r"\d\s*(?:cm|mm|ft)(?![a-z])|\d\s*(?:in\.|inch|inches)(?!\w)", re.I)


def find_size(text):
    """(line, unit) of the first size line: 'metric', 'inches' or (None, None)."""
    lines = fact_lines(text)
    for line in lines:
        if DIMENSIONS.search(line):
            return line, "metric"
    for line in lines:
        if INCH_SIZE.search(line):
            return line, "inches"
    return None, None


def extract_facts(text):
    """Best-effort dimensions / medium / year from the English description."""
    facts = {"dimensions": None, "medium": None, "year_created": None}
    lines = fact_lines(text)
    for i, line in enumerate(lines):
        if DIMENSIONS.search(line):
            facts["dimensions"] = line
            j = i - 1  # medium is usually the line above the size ...
            while j >= 0 and SIGNATURE_LINE.match(lines[j]):
                j -= 1  # ... unless "signed / dated" lines sit in between
            if j >= 1 and len(lines[j]) <= 100 and MEDIUM_WORDS.search(lines[j]):
                facts["medium"] = lines[j].rstrip(" ;,")
            break
    year = YEAR_AFTER_VERB.search(text or "") or YEAR_AFTER_DATED.search(text or "")
    if year:
        facts["year_created"] = to_int(year.group(1))
    return facts


def infer_medium(text):
    """Looser medium search, used only when extract_facts() found none.

    Looks up to 3 lines above the size line (skipping signature lines, never line 0 = artist).
    """
    lines = fact_lines(text)
    for i, line in enumerate(lines):
        if DIMENSIONS.search(line):
            looked = 0
            for j in range(i - 1, 0, -1):
                if SIGNATURE_LINE.match(lines[j]):
                    continue
                looked += 1
                if len(lines[j]) <= 100 and MEDIUM_WORDS.search(lines[j]):
                    return lines[j].rstrip(" ;,")
                if looked >= 3:
                    break
            return None
    return None


def facts_from_text(description_en, catalogue_note=""):
    """What can be filled from text ALREADY in the csv, with no request.

    Returns (values, flags): literature / exhibited / provenance from sub-headings in the note
    or description, dimensions from the description (glued lines and inch-only sizes included).
    """
    values, flags = {}, []
    for source, label in ((catalogue_note, "note"), (description_en, "description")):
        for name, text in split_subsections(source).items():
            if name not in values:
                values[name] = text
                flags.append(f"{name}_from_{label}")
    line, unit = find_size(description_en)
    if line:
        values["dimensions"] = line
        if unit == "inches":
            flags.append("dimensions_inches_only")
    return values, flags
