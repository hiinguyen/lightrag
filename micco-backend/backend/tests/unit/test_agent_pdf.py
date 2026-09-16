"""Unit tests for rendering an n8n AI Agent's markdown answer to PDF."""
from __future__ import annotations

import fitz

from app.services.agent_pdf import render_markdown_to_pdf


def test_render_markdown_to_pdf_produces_a_valid_pdf_document():
    pdf_bytes = render_markdown_to_pdf(
        title="Tóm tắt tài liệu",
        content_markdown="# Mục 1\n\nNội dung tóm tắt bằng tiếng Việt có dấu.",
    )

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 0


def test_render_markdown_to_pdf_handles_multiple_paragraphs_and_blank_lines():
    pdf_bytes = render_markdown_to_pdf(
        title="Báo cáo",
        content_markdown="Đoạn một.\n\nĐoạn hai sau dòng trống.",
    )

    assert pdf_bytes.startswith(b"%PDF")


def test_render_markdown_to_pdf_preserves_consecutive_lines_and_bullet_list():
    """Regression test: two consecutive non-blank multi_cell calls (e.g. a
    bullet list) used to crash with FPDFException because the cursor was left
    at the right margin after each call. Extract the rendered text back out
    with PyMuPDF and assert the real content survived, not just that PDF
    bytes were produced.
    """
    pdf_bytes = render_markdown_to_pdf(
        title="Báo cáo",
        content_markdown=(
            "# Mục 1\nNội dung.\n- gạch đầu dòng một\n- gạch đầu dòng hai"
        ),
    )

    assert pdf_bytes.startswith(b"%PDF")

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        extracted_text = "\n".join(page.get_text() for page in doc)

    assert "Mục 1" in extracted_text
    assert "Nội dung." in extracted_text
    assert "gạch đầu dòng một" in extracted_text
    assert "gạch đầu dòng hai" in extracted_text


def test_render_markdown_to_pdf_skips_empty_heading_line():
    pdf_bytes = render_markdown_to_pdf(
        title="Báo cáo",
        content_markdown="#\nNội dung sau heading rỗng.",
    )

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        extracted_text = "\n".join(page.get_text() for page in doc)

    assert "Nội dung sau heading rỗng." in extracted_text


def test_render_markdown_to_pdf_renders_bold_text_without_asterisks():
    pdf_bytes = render_markdown_to_pdf(
        title="Báo cáo",
        content_markdown="**Base URL:** địa chỉ endpoint mặc định.",
    )

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        extracted_text = "\n".join(page.get_text() for page in doc)

    assert "Base URL:" in extracted_text
    assert "**" not in extracted_text


def test_render_markdown_to_pdf_renders_nested_heading_levels():
    pdf_bytes = render_markdown_to_pdf(
        title="Báo cáo",
        content_markdown="## Mục 2\n\n### Mục 2.1\n\nNội dung chi tiết.",
    )

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        extracted_text = "\n".join(page.get_text() for page in doc)

    assert "Mục 2" in extracted_text
    assert "Mục 2.1" in extracted_text
    assert "Nội dung chi tiết." in extracted_text
    assert "##" not in extracted_text


def test_render_markdown_to_pdf_renders_list_immediately_after_paragraph_as_bullets():
    """Regression test: the n8n AI Agent's markdown often has no blank line
    between a preceding paragraph/bold line and a following list, which
    python-markdown (unlike CommonMark) refuses to parse as a real list —
    the '-' markers used to leak through as literal text instead of bullets.
    """
    pdf_bytes = render_markdown_to_pdf(
        title="Báo cáo",
        content_markdown=(
            "**Cách kết nối:**\n"
            "- mục một\n"
            "- mục hai\n"
        ),
    )

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        extracted_text = "\n".join(page.get_text() for page in doc)

    assert "mục một" in extracted_text
    assert "mục hai" in extracted_text
    assert "\n- mục một" not in extracted_text


def test_render_markdown_to_pdf_strips_image_markdown():
    """Image markdown is stripped rather than rendered: the AI Agent has no
    real image to attach, and fetching a hallucinated URL would be SSRF risk.
    """
    pdf_bytes = render_markdown_to_pdf(
        title="Báo cáo",
        content_markdown=(
            "Nội dung chính.\n\n"
            "![Kiến trúc kết nối client OpenAI-compatible với 9Router]"
        ),
    )

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        extracted_text = "\n".join(page.get_text() for page in doc)

    assert "Nội dung chính." in extracted_text
    assert "![" not in extracted_text
