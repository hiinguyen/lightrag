"""Splitting an extracted document into addressable sections.

Lets the Telegram agent answer "tóm tắt phần điều khoản thanh toán" by
fetching one section instead of the whole file, on documents that are not
indexed yet. Headings follow Vietnamese document conventions (PHẦN, CHƯƠNG,
MỤC, Điều N, numbered clauses) plus markdown.
"""
from __future__ import annotations

from app.services.document_sections import split_into_sections


def test_split_returns_one_section_when_no_heading_is_found():
    sections = split_into_sections("Một đoạn văn xuôi không có tiêu đề nào cả.")

    assert len(sections) == 1
    assert sections[0].content == "Một đoạn văn xuôi không có tiêu đề nào cả."


def test_split_returns_nothing_for_empty_text():
    assert split_into_sections("") == []
    assert split_into_sections("   \n  ") == []


def test_split_detects_dieu_headings():
    text = (
        "Điều 1. Phạm vi áp dụng\n"
        "Hợp đồng này áp dụng cho toàn bộ đơn hàng.\n"
        "Điều 2. Thanh toán\n"
        "Bên A thanh toán trong vòng 30 ngày.\n"
    )

    sections = split_into_sections(text)

    assert [s.heading for s in sections] == ["Điều 1. Phạm vi áp dụng", "Điều 2. Thanh toán"]
    assert "30 ngày" in sections[1].content


def test_split_detects_chuong_and_phan_headings():
    text = "PHẦN I. QUY ĐỊNH CHUNG\nNội dung phần một.\nCHƯƠNG 2: TỔ CHỨC\nNội dung chương hai.\n"

    sections = split_into_sections(text)

    assert [s.heading for s in sections] == ["PHẦN I. QUY ĐỊNH CHUNG", "CHƯƠNG 2: TỔ CHỨC"]


def test_split_detects_numbered_and_markdown_headings():
    text = "# Báo cáo quý IV\nMở đầu báo cáo.\n2.1 Doanh thu\nDoanh thu đạt 12 tỷ.\n"

    sections = split_into_sections(text)

    assert [s.heading for s in sections] == ["# Báo cáo quý IV", "2.1 Doanh thu"]


def test_split_keeps_text_before_the_first_heading():
    text = "Công ty Micco\nĐiều 1. Phạm vi\nNội dung điều một.\n"

    sections = split_into_sections(text)

    assert len(sections) == 2
    assert sections[0].heading is None
    assert "Công ty Micco" in sections[0].content
    assert sections[1].heading == "Điều 1. Phạm vi"


def test_split_includes_the_heading_line_in_its_own_content():
    text = "Điều 3. Bảo mật\nHai bên giữ bí mật thông tin.\n"

    sections = split_into_sections(text)

    assert sections[0].content.startswith("Điều 3. Bảo mật")
    assert "giữ bí mật" in sections[0].content


def test_split_ignores_a_long_line_that_merely_starts_like_a_heading():
    long_line = (
        "Điều này không phải tiêu đề mà là một câu văn rất dài kể lại toàn bộ quá trình "
        "thương thảo hợp đồng giữa hai bên trong suốt nhiều tháng liền và vẫn tiếp tục."
    )

    sections = split_into_sections(long_line)

    assert len(sections) == 1
    assert sections[0].heading is None
