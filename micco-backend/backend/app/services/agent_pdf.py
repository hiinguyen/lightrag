"""Render an n8n AI Agent's markdown answer to a PDF for email attachment.

Uses fpdf2 (pure Python, no system libraries like cairo/pango — lighter than
weasyprint for the Docker image) with a bundled Vietnamese-capable font,
since the summarized content is Vietnamese document text.

Not a full markdown renderer: '#'/'##' lines become bold headings, blank
lines become spacing, everything else is a plain paragraph. Good enough for
an LLM-generated summary, not a general-purpose document converter.
"""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_FONT_REGULAR = _FONT_DIR / "DejaVuSans.ttf"
_FONT_BOLD = _FONT_DIR / "DejaVuSans-Bold.ttf"


def render_markdown_to_pdf(title: str, content_markdown: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("DejaVu", "", str(_FONT_REGULAR))
    pdf.add_font("DejaVu", "B", str(_FONT_BOLD))

    pdf.set_font("DejaVu", "B", 16)
    pdf.multi_cell(0, 10, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    for line in content_markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            pdf.ln(4)
            continue
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if not heading:
                continue
            pdf.set_font("DejaVu", "B", 13)
            pdf.multi_cell(0, 8, heading, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        else:
            pdf.set_font("DejaVu", "", 11)
            pdf.multi_cell(0, 7, stripped, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output())
