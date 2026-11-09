"""Turning page HTML into clean lines of text. Used by every lot-page parser.

No knowledge of lots or columns here: only text clean-up.
"""

import html
import re

TAGS = re.compile(r"<[^>]+>")

# Tags that end a line. Only </p> and <br> before; block tags such as </div> and </li> glued
# lines together ("Measuring 90 x 55mmFrench assay mark ...").
LINE_BREAKS = re.compile(r"</p>|<br\s*/?>|</div>|</li>|<li[^>]*>|</h[1-6]>|</tr>|<hr\s*/?>", re.I)

# Separates the English text from the translation: a line of dashes OR underscores
# (the Paris sales use "______").
DASH_LINE = re.compile(r"\n\s*[-_–—]{10,}\s*\n")

# Where a word starts right after the previous one with no space ("numberedCirca").
GLUED = re.compile(r"(?<=[a-z0-9.)])(?=[A-Z][a-z]{2,})")


def visible_lines(response):
    """Visible page text, one stripped string per text node."""
    nodes = response.xpath("//body//text()[not(ancestor::script) and not(ancestor::style)]")
    return [text.strip() for text in nodes.getall() if text.strip()]


def html_to_text(value):
    """og:description holds HTML such as <p>..</p>; make it plain lines."""
    value = LINE_BREAKS.sub("\n", value or "")
    value = html.unescape(TAGS.sub("", value)).replace("\xa0", " ")
    lines = [line.strip() for line in value.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def fact_lines(text):
    """Lines of `text`, with glued lines split again. Used only to FIND facts; stored text is unchanged."""
    lines = []
    for line in (text or "").split("\n"):
        lines.extend(part.strip() for part in GLUED.split(line) if part.strip())
    return lines


def join_fragments(lines):
    """Inline tags split one sentence over several lines; glue them back."""
    groups = []
    for line in lines:
        if groups and line[0] in ",.;:)":
            groups[-1].append(line)
        elif groups and line[0].islower():
            groups[-1].append(" " + line)
        else:
            groups.append([line])
    return "\n".join("".join(group) for group in groups)


def heading_key(line):
    return line.lower().strip().rstrip(" :").strip()


def english_part(text):
    """The English text before a '------' / '______' line (the translation follows it)."""
    return DASH_LINE.split(text or "", maxsplit=1)[0].strip()
