"""Summarise a document once, at upload, for the approval group chat.

Runs on the write path rather than the read path: one LLM call per uploaded
document instead of one per question, and the summary is already in the
notification when the approvers first see it.

Long documents are handled map-reduce — summarise each chunk, then summarise
those summaries — because the alternative, truncating at a fixed cap, silently
drops whatever sits at the end of a long contract. SUMMARY_MAX_CHUNKS bounds
what a single upload can cost: a 500-page scan must not turn into an
open-ended LLM bill.

Errors propagate. The caller decides that a summary is best-effort; swallowing
failures here would make an LLM outage indistinguishable from a document that
genuinely has nothing to summarise.
"""
from __future__ import annotations

import logging

from app.services.document_text_extractor import extract_full_text
from app.services.llm import get_llm_provider
from app.services.llm.types import LLMMessage, LLMResult

logger = logging.getLogger(__name__)

SUMMARY_CHUNK_CHARS = 12_000
SUMMARY_MAX_CHUNKS = 8
SUMMARY_MAX_TOKENS = 700
SUMMARY_SOURCE_MAX_CHARS = SUMMARY_CHUNK_CHARS * SUMMARY_MAX_CHUNKS

_SYSTEM_PROMPT = (
    "Bạn là trợ lý tóm tắt tài liệu nội bộ của doanh nghiệp. "
    "Chỉ tóm tắt dựa trên nội dung được cung cấp, tuyệt đối không suy diễn hay bịa thêm. "
    "Trả lời bằng tiếng Việt, ngắn gọn, đúng trọng tâm."
)

_WHOLE_PROMPT = (
    "Tóm tắt tài liệu sau cho người có thẩm quyền phê duyệt: nêu mục đích, các nội dung "
    "chính và những điểm cần chú ý. Dùng gạch đầu dòng ngắn.\n\n"
    "--- NỘI DUNG ---\n{content}"
)

_MAP_PROMPT = (
    "Đây là một phần của tài liệu dài. Tóm tắt các ý chính của riêng phần này bằng gạch "
    "đầu dòng ngắn, giữ lại số liệu, mốc thời gian và điều khoản quan trọng.\n\n"
    "--- NỘI DUNG ---\n{content}"
)

_REDUCE_PROMPT = (
    "Dưới đây là các bản tóm tắt từng phần của cùng một tài liệu, theo đúng thứ tự. Hãy gộp "
    "thành một bản tóm tắt thống nhất cho toàn bộ tài liệu: nêu mục đích, các nội dung chính "
    "và những điểm người phê duyệt cần chú ý. Không lặp lại trùng ý.\n\n"
    "--- CÁC TÓM TẮT THÀNH PHẦN ---\n{content}"
)


async def summarize_text(text: str) -> str | None:
    """Summarise *text* in Vietnamese, or return None if there is nothing to summarise."""
    if not text or not text.strip():
        return None

    if len(text) <= SUMMARY_CHUNK_CHARS:
        return await _complete(_WHOLE_PROMPT.format(content=text))

    chunks = _split_into_chunks(text)
    logger.info(f"document summary: map-reduce over {len(chunks)} chunk(s)")

    partials = [await _complete(_MAP_PROMPT.format(content=chunk)) for chunk in chunks]
    joined = "\n\n".join(
        f"[Phần {index}]\n{partial}" for index, partial in enumerate(partials, start=1)
    )
    return await _complete(_REDUCE_PROMPT.format(content=joined))


async def ensure_document_summary(db, document) -> str | None:
    """Summarise *document* and persist it, unless it already has a summary.

    Returns None when there is nothing to summarise — an unsupported file
    type, a file missing from disk, or an empty extraction. LLM failures are
    not caught here; the caller decides how much a missing summary matters.
    """
    if document.summary:
        return document.summary

    # Imported here because app.api.documents imports this package's siblings.
    from app.api.documents import UPLOAD_DIR

    file_path = UPLOAD_DIR / document.filename
    if not file_path.exists():
        logger.info(f"document summary: file for document {document.id} is not on disk")
        return None

    extracted = await extract_full_text(
        file_path, document.file_type, max_chars=SUMMARY_SOURCE_MAX_CHARS
    )
    if not extracted.supported or not extracted.content:
        logger.info(
            f"document summary: no extractable text for document {document.id} "
            f"({document.file_type})"
        )
        return None

    summary = await summarize_text(extracted.content)
    if summary:
        document.summary = summary
        await db.commit()
        logger.info(f"document summary: stored {len(summary)} chars for document {document.id}")

    return summary


def _split_into_chunks(text: str) -> list[str]:
    """Slice *text* into at most SUMMARY_MAX_CHUNKS pieces, preferring line breaks."""
    chunks: list[str] = []
    start = 0

    while start < len(text) and len(chunks) < SUMMARY_MAX_CHUNKS:
        end = start + SUMMARY_CHUNK_CHARS
        if end < len(text):
            boundary = text.rfind("\n", start, end)
            # A boundary in the first half means the text has almost no line
            # breaks; slicing there would produce many tiny chunks.
            if boundary > start + SUMMARY_CHUNK_CHARS // 2:
                end = boundary
        chunks.append(text[start:end])
        start = end

    return chunks


async def _complete(prompt: str) -> str:
    provider = get_llm_provider()
    result = await provider.acomplete(
        [LLMMessage(role="user", content=prompt)],
        max_tokens=SUMMARY_MAX_TOKENS,
        system_prompt=_SYSTEM_PROMPT,
    )
    return (result.content if isinstance(result, LLMResult) else result).strip()
