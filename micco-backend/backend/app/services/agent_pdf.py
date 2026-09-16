"""Render an n8n AI Agent's markdown answer to a PDF for email attachment.

Uses fpdf2 (pure Python, no system libraries like cairo/pango — lighter than
weasyprint for the Docker image) with a bundled Vietnamese-capable font,
since the summarized content is Vietnamese document text.

Markdown is converted to HTML via python-markdown, then rendered through
fpdf2's HTML writer — so headings, bold/italic emphasis, and bullet/numbered
lists render properly instead of showing raw `#`/`**`/`-` characters. There is
no italic TTF bundled, so italic styles fall back to the regular weight
instead of crashing on unknown font styles.

The AI Agent's markdown often omits the blank line Markdown.pl-style parsers
require before a list starts right after a paragraph (a known python-markdown
quirk, unlike CommonMark), which otherwise leaves list items as literal `-`
text instead of real bullets — so that blank line is inserted before
conversion. Image references are stripped rather than rendered: the AI has no
real image to attach, and fetching whatever URL it hallucinates would be an
SSRF risk.
"""
from __future__ import annotations

import re
from pathlib import Path

import markdown
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from fpdf.fonts import TextStyle
from fpdf.html import HTML2FPDF

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_FONT_REGULAR = _FONT_DIR / "DejaVuSans.ttf"
_FONT_BOLD = _FONT_DIR / "DejaVuSans-Bold.ttf"

_BODY_FONT_SIZE = 11

# fpdf2's write_html() only fills in its own default top/bottom/left margins
# for a tag when the override passed in tag_styles is a plain FontFace; since
# these overrides are TextStyle instances (needed to set font_family), they
# replace the defaults outright, so the spacing between blocks (heading vs.
# body, one paragraph vs. the next, one bullet vs. the next) must be set
# explicitly here too — otherwise every block sits flush against the next
# with no gap, which is what made the PDF look cramped.
#
# For HEADING_TAGS specifically, fpdf2 scales `b_margin` by the heading's own
# font size (b_margin * font_size_pt / pdf.k) before applying it — unlike
# every other tag, where the margin is used as a literal mm value — so a
# small fraction here (matching fpdf2's own default of 0.4) is what actually
# produces a normal-looking gap; a literal mm value like the other tags use
# ends up several times too large.
_HEADING_B_MARGIN = 0.4

_TAG_STYLES = {
    "h1": TextStyle(
        font_family="DejaVu", font_style="B", font_size_pt=16, t_margin=6, b_margin=_HEADING_B_MARGIN
    ),
    "h2": TextStyle(
        font_family="DejaVu", font_style="B", font_size_pt=14, t_margin=5, b_margin=_HEADING_B_MARGIN
    ),
    "h3": TextStyle(
        font_family="DejaVu", font_style="B", font_size_pt=12, t_margin=4, b_margin=_HEADING_B_MARGIN
    ),
    "h4": TextStyle(
        font_family="DejaVu",
        font_style="B",
        font_size_pt=_BODY_FONT_SIZE,
        t_margin=3,
        b_margin=_HEADING_B_MARGIN,
    ),
    "p": TextStyle(font_family="DejaVu", font_size_pt=_BODY_FONT_SIZE, b_margin=3),
    "li": TextStyle(font_family="DejaVu", font_size_pt=_BODY_FONT_SIZE, l_margin=5, b_margin=3),
    "blockquote": TextStyle(
        font_family="DejaVu", font_style="I", font_size_pt=_BODY_FONT_SIZE, l_margin=5, t_margin=3, b_margin=3
    ),
    "code": TextStyle(font_family="DejaVu", font_size_pt=_BODY_FONT_SIZE - 1),
}

# Extra leading within a wrapped paragraph/list item/heading — 1.0 (fpdf2's
# default) packs Vietnamese diacritics against the line below, so bump it.
_LINE_HEIGHT = 1.35

_MARKDOWN_EXTENSIONS = ["sane_lists", "nl2br", "tables"]

_IMAGE_MARKDOWN_RE = re.compile(r"!\[[^\]]*\](\([^)]*\))?")
_LIST_ITEM_RE = re.compile(r"^\s{0,3}([-*+]|\d+[.)])\s+")
_LINE_HEIGHT_TAG_RE = re.compile(r"<(p|li|h[1-4]|blockquote)>")


def _strip_image_markdown(text: str) -> str:
    return _IMAGE_MARKDOWN_RE.sub("", text)


def _apply_line_height(html: str) -> str:
    """Set an inline `line-height` style on each block tag.

    fpdf2's HTML writer only reads `line-height` per-element from the tag's
    own `style`/`line-height` attribute, not from an ancestor — python-markdown
    never emits either, so its default (single-spaced) is used unless we add
    it here ourselves.
    """
    return _LINE_HEIGHT_TAG_RE.sub(rf'<\1 style="line-height: {_LINE_HEIGHT}">', html)


class _HTML2FPDF(HTML2FPDF):
    """Work around an fpdf2 quirk where a preceding heading's font size leaks
    into a later list's bullet/number marker.

    fpdf2 tracks two separate "current font size" values while parsing HTML:
    an internal one it updates correctly on every tag (used for the actual
    text), and `pdf.font_size_pt` itself, which a heading's write temporarily
    bumps but never resets afterwards — every write after that happens inside
    a push/pop'd local graphics state, so the change never sticks except for
    headings. A `<ol>`/`<ul>` bullet marker is sized directly from that second,
    stale value, so any heading anywhere earlier in the document makes every
    later list's numbers/bullets render at the heading's font size instead of
    the list's own. Re-syncing it right before `<ol>`/`<ul>`/`<li>` fixes that.
    """

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("ol", "ul", "li"):
            self.pdf.set_font(
                family=self.font_family or self.pdf.font_family,
                size=self.font_size_pt,
                style=self.font_emphasis.style,
            )
        super().handle_starttag(tag, attrs)


def _ensure_blank_line_before_lists(text: str) -> str:
    lines = text.split("\n")
    normalized: list[str] = []
    for line in lines:
        previous_line = normalized[-1] if normalized else ""
        starts_list = bool(_LIST_ITEM_RE.match(line))
        previous_is_list_item = bool(_LIST_ITEM_RE.match(previous_line))
        if starts_list and previous_line.strip() and not previous_is_list_item:
            normalized.append("")
        normalized.append(line)
    return "\n".join(normalized)


def render_markdown_to_pdf(title: str, content_markdown: str) -> bytes:
    pdf = FPDF()
    pdf.HTML2FPDF_CLASS = _HTML2FPDF
    pdf.add_page()
    pdf.add_font("DejaVu", "", str(_FONT_REGULAR))
    pdf.add_font("DejaVu", "B", str(_FONT_BOLD))
    # No italic TTF is bundled; alias I/BI to the closest available weight so
    # markdown emphasis (*text*, _text_) doesn't crash on an undefined style.
    pdf.add_font("DejaVu", "I", str(_FONT_REGULAR))
    pdf.add_font("DejaVu", "BI", str(_FONT_BOLD))

    pdf.set_font("DejaVu", "B", 18)
    pdf.multi_cell(0, 10, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    normalized_markdown = _ensure_blank_line_before_lists(
        _strip_image_markdown(content_markdown)
    )
    html = _apply_line_height(
        markdown.markdown(normalized_markdown, extensions=_MARKDOWN_EXTENSIONS)
    )
    pdf.set_font("DejaVu", "", _BODY_FONT_SIZE)
    pdf.write_html(html, font_family="DejaVu", tag_styles=_TAG_STYLES)

    return bytes(pdf.output())
