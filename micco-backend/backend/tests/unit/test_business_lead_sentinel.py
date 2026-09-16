"""Stripping the lead-handoff sentinel out of a streaming answer.

Sibling of tests/unit/test_business_recommendation.py. The property under
test is the same: the marker must never reach the screen, no matter where
chunk boundaries fall, and a malformed body must fail closed to "no lead".
"""
from __future__ import annotations

import pytest

from app.services.business_lead_sentinel import (
    SENTINEL_OPEN,
    LeadDraft,
    LeadSentinelFilter,
)


def run(chunks: list[str]) -> tuple[str, LeadDraft | None]:
    """Feed `chunks` through the filter; return (displayed text, draft)."""
    sentinel = LeadSentinelFilter()
    shown = "".join(sentinel.feed(chunk) for chunk in chunks)
    trailing, draft = sentinel.finish()
    return shown + trailing, draft


# ─── The marker never reaches the screen ───────────────────────────

def test_sentinel_is_stripped_from_a_single_chunk():
    shown, draft = run(["Vâng, tôi ghi nhận nhu cầu.[[LEAD: 3,7|Cần 200 tấn anfo, ngân sách 200 triệu]]"])

    assert shown == "Vâng, tôi ghi nhận nhu cầu."
    assert draft == LeadDraft(summary="Cần 200 tấn anfo, ngân sách 200 triệu", package_ids=[3, 7])


def test_sentinel_split_across_every_possible_boundary_never_leaks():
    answer = "Vâng, tôi ghi nhận nhu cầu."
    full = f"{answer}[[LEAD: 3|Cần tư vấn hợp đồng]]"

    for split in range(len(full) + 1):
        shown, draft = run([full[:split], full[split:]])
        assert shown == answer, f"leaked at split {split}: {shown!r}"
        assert draft == LeadDraft(summary="Cần tư vấn hợp đồng", package_ids=[3])


def test_sentinel_fed_one_character_at_a_time_never_leaks():
    shown, draft = run(list("Đã rõ.[[LEAD: 1|Muốn ký hợp đồng]]"))

    assert shown == "Đã rõ."
    assert draft == LeadDraft(summary="Muốn ký hợp đồng", package_ids=[1])


def test_partial_marker_is_held_back_until_it_is_disproved():
    sentinel = LeadSentinelFilter()

    assert sentinel.feed("Đã rõ.[[LE") == "Đã rõ."
    assert sentinel.feed("AD: 1|Cần báo giá]]") == ""
    trailing, draft = sentinel.finish()
    assert trailing == ""
    assert draft == LeadDraft(summary="Cần báo giá", package_ids=[1])


def test_text_that_looked_like_a_marker_is_released_at_finish():
    shown, draft = run(["Giá theo m[[3", ""])

    assert shown == "Giá theo m[[3"
    assert draft is None


def test_truncated_sentinel_is_dropped_not_shown():
    shown, draft = run(["Đã rõ.[[LEAD: 1|Cần báo giá"])

    assert shown == "Đã rõ."
    assert draft is None


# ─── Parsing ───────────────────────────────────────────────────────

def test_ids_before_the_pipe_are_parsed_loosely():
    _, draft = run(["Xong.[[LEAD: 3, 7 ,12|Cần tư vấn]]"])

    assert draft == LeadDraft(summary="Cần tư vấn", package_ids=[3, 7, 12])


def test_empty_ids_before_the_pipe_yields_no_packages():
    """The customer may want to buy without naming a specific package."""
    _, draft = run(["Xong.[[LEAD: |Cần tư vấn hợp đồng tổng thể]]"])

    assert draft == LeadDraft(summary="Cần tư vấn hợp đồng tổng thể", package_ids=[])


def test_missing_pipe_is_malformed_and_drops_the_lead():
    """Fail closed: a body with no '|' cannot be split into ids and summary."""
    shown, draft = run(["Xong.[[LEAD: chỉ có ids không có tóm tắt]]"])

    assert shown == "Xong."
    assert draft is None


def test_empty_summary_after_the_pipe_drops_the_lead():
    _, draft = run(["Xong.[[LEAD: 1|   ]]"])

    assert draft is None


def test_summary_may_itself_contain_a_pipe_character():
    """Only the first '|' is a delimiter; the rest belongs to the summary."""
    _, draft = run(["Xong.[[LEAD: 1|Cần A|B|C]]"])

    assert draft == LeadDraft(summary="Cần A|B|C", package_ids=[1])


def test_a_second_sentinel_is_ignored_the_first_wins():
    shown, draft = run(["A.[[LEAD: 1|Đầu tiên]]B.[[LEAD: 2|Thứ hai]]"])

    assert shown == "A.B."
    assert draft == LeadDraft(summary="Đầu tiên", package_ids=[1])


def test_runaway_marker_is_released_as_text_rather_than_buffered_forever():
    tail = "x" * 700
    shown, draft = run([f"Mở ngoặc [[LEAD: {tail}"])

    assert tail in shown
    assert draft is None


def test_answer_without_a_sentinel_passes_through_untouched():
    text = "Micco cung cấp thuốc nổ công nghiệp cho mỏ đá lộ thiên."

    shown, draft = run([text])

    assert shown == text
    assert draft is None
