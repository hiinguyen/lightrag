"""Map-reduce summarisation for the approval notification.

The summary is generated once per upload, in the background, so the group
chat reads it without paying an LLM call per question. Long documents are
summarised in chunks and then reduced, under a hard cap on how many LLM
calls a single upload may cost.
"""
from __future__ import annotations

import pytest

from app.services import document_summarizer
from app.services.document_summarizer import (
    SUMMARY_CHUNK_CHARS,
    SUMMARY_MAX_CHUNKS,
    summarize_text,
)


class FakeSummaryProvider:
    """Records what was sent and answers "tóm tắt <n>" for the nth call."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.raises: Exception | None = None

    async def acomplete(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if self.raises is not None:
            raise self.raises
        return f"tóm tắt {len(self.calls)}"

    @property
    def prompts(self) -> list[str]:
        return [call["messages"][0].content for call in self.calls]


@pytest.fixture
def fake_llm(monkeypatch) -> FakeSummaryProvider:
    provider = FakeSummaryProvider()
    monkeypatch.setattr(document_summarizer, "get_llm_provider", lambda: provider)
    return provider


async def test_summarize_text_returns_none_for_empty_text(fake_llm):
    assert await summarize_text("") is None
    assert fake_llm.calls == []


async def test_summarize_text_returns_none_for_whitespace_only_text(fake_llm):
    assert await summarize_text("   \n\t  ") is None
    assert fake_llm.calls == []


async def test_summarize_text_makes_a_single_call_for_a_short_document(fake_llm):
    summary = await summarize_text("Hợp đồng cung cấp thuốc nổ công nghiệp.")

    assert len(fake_llm.calls) == 1
    assert summary == "tóm tắt 1"


async def test_summarize_text_sends_the_document_to_the_model(fake_llm):
    await summarize_text("Điều 1. Phạm vi áp dụng của hợp đồng.")

    assert "Điều 1. Phạm vi áp dụng của hợp đồng." in fake_llm.prompts[0]


async def test_summarize_text_maps_each_chunk_then_reduces(fake_llm):
    text = "a" * (SUMMARY_CHUNK_CHARS * 2 + 100)

    await summarize_text(text)

    # Three chunks mapped, then one reduce over their summaries.
    assert len(fake_llm.calls) == 4


async def test_summarize_text_reduce_step_sees_every_partial_summary(fake_llm):
    text = "b" * (SUMMARY_CHUNK_CHARS * 2 + 100)

    await summarize_text(text)

    reduce_prompt = fake_llm.prompts[-1]
    assert "tóm tắt 1" in reduce_prompt
    assert "tóm tắt 2" in reduce_prompt
    assert "tóm tắt 3" in reduce_prompt


async def test_summarize_text_returns_the_reduced_summary(fake_llm):
    text = "c" * (SUMMARY_CHUNK_CHARS * 2 + 100)

    summary = await summarize_text(text)

    assert summary == "tóm tắt 4"


async def test_summarize_text_caps_how_many_llm_calls_one_upload_can_cost(fake_llm):
    text = "d" * (SUMMARY_CHUNK_CHARS * (SUMMARY_MAX_CHUNKS + 5))

    await summarize_text(text)

    assert len(fake_llm.calls) == SUMMARY_MAX_CHUNKS + 1


async def test_summarize_text_prefers_to_split_on_a_line_boundary(fake_llm):
    paragraph = "Điều khoản thanh toán của hợp đồng.\n"
    text = paragraph * (SUMMARY_CHUNK_CHARS // len(paragraph) + 50)

    await summarize_text(text)

    assert fake_llm.prompts[0].rstrip().endswith("hợp đồng.")


async def test_summarize_text_propagates_an_llm_failure(fake_llm):
    fake_llm.raises = RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError):
        await summarize_text("Nội dung tài liệu cần tóm tắt.")
