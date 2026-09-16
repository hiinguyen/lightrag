"""Chat for the external B2B portal.

The customer-facing counterpart of ``app.api.chat_agent``, deliberately not
built on it:

- A request carries only a message. The workspace, the document scope, the
  retrieval mode and the conversation history all come from the server, so a
  customer cannot widen retrieval and cannot forge an assistant turn to talk
  the model past its guardrail. ``ChatRequest`` (``app/schemas/rag.py``) trusts
  all four of those from the client.
- Retrieval goes through ``app.services.business_rag``, the single place that
  decides which published documents exist. Nothing here re-derives that.
- Only plain text reaches the customer. Thinking chunks can quote the retrieved
  context verbatim, so they are dropped rather than streamed.

The generator yields ``(event_name, payload)`` tuples rather than formatted SSE
frames, so the ordering and the payload shape can be asserted in tests without
parsing a stream.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import AsyncGenerator, Iterator

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.business_chat_prompt import (
    NO_PUBLISHED_CONTENT_ANSWER,
    OUT_OF_SCOPE_ANSWER,
    build_business_system_prompt,
)
from app.models.chat_message import ChatMessage
from app.models.user import User
from app.services.business_packages import (
    build_catalog_digest,
    get_active_packages,
    resolve_recommendations,
    to_card,
)
from app.services.business_lead_sentinel import LeadSentinelFilter
from app.services.business_rag import business_search, get_business_workspace
from app.services.business_recommendation import RecommendationSentinelFilter
from app.services.llm import get_llm_provider
from app.services.llm.types import LLMMessage

logger = logging.getLogger(__name__)

# How much of the conversation is replayed to the model. Read from the server,
# never from the request.
MAX_HISTORY_MESSAGES = 10

# Upper bound on what /history returns, so one long-running conversation cannot
# turn into an unbounded response.
MAX_HISTORY_PAGE = 200

LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 2048

_STATUS_RETRIEVING = "Đang tra cứu tài liệu Micco"
_STATUS_GENERATING = "Đang soạn câu trả lời"

# Shown to the customer when generation breaks. Fixed text: an exception message
# can name a provider, a model or an internal host.
_ERROR_MESSAGE = "Hệ thống đang gặp sự cố khi trả lời. Bạn vui lòng thử lại sau ít phút."

_PERSISTED_ROLES = ("user", "assistant")


# ─── History (server-side) ─────────────────────────────────────────

async def load_business_messages(
    db: AsyncSession,
    workspace_id: int,
    user_id: int,
    limit: int = MAX_HISTORY_PAGE,
) -> list[ChatMessage]:
    """The customer's own messages, oldest first.

    Scoped by user_id as well as workspace_id: every portal customer shares the
    one business workspace, so the user filter is what keeps one customer's
    conversation out of another's.
    """
    result = await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.workspace_id == workspace_id,
            ChatMessage.user_id == user_id,
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def clear_business_history(
    db: AsyncSession, workspace_id: int, user_id: int
) -> int:
    """Delete the customer's conversation. Returns how many rows went."""
    result = await db.execute(
        delete(ChatMessage).where(
            ChatMessage.workspace_id == workspace_id,
            ChatMessage.user_id == user_id,
        )
    )
    await db.commit()
    return result.rowcount or 0


async def _to_llm_history(
    db: AsyncSession, workspace_id: int, user_id: int
) -> list[LLMMessage]:
    rows = await load_business_messages(
        db, workspace_id, user_id, limit=MAX_HISTORY_MESSAGES
    )
    return [
        LLMMessage(role=row.role, content=row.content)
        for row in rows
        if row.role in _PERSISTED_ROLES and row.content
    ]


async def _persist(
    db: AsyncSession,
    workspace_id: int,
    user_id: int,
    role: str,
    content: str,
    sources: list[dict] | None = None,
    recommended_packages: list[dict] | None = None,
) -> str:
    """Store one turn. Best-effort: a failure here must not kill the answer."""
    message_id = str(uuid.uuid4())
    try:
        db.add(
            ChatMessage(
                workspace_id=workspace_id,
                user_id=user_id,
                message_id=message_id,
                role=role,
                content=content,
                sources=sources or None,
                recommended_packages=recommended_packages or None,
            )
        )
        await db.commit()
    except Exception:
        logger.warning("business chat: failed to persist %s message", role, exc_info=True)
        await db.rollback()
    return message_id


# ─── Streaming ─────────────────────────────────────────────────────

def _fixed_answer_events(
    answer: str, message_id: str | None = None
) -> Iterator[tuple[str, dict]]:
    """Emit a canned answer through the same event sequence as a streamed one.

    The client renders one code path whether the text came from the model or
    from a constant, and no LLM call is made for an answer we already know.
    """
    yield ("delta", {"text": answer})
    yield (
        "complete",
        {"message_id": message_id or "", "answer": answer, "sources": []},
    )


async def stream_business_chat(
    db: AsyncSession, user: User, question: str
) -> AsyncGenerator[tuple[str, dict], None]:
    """Answer a customer question from published content only.

    Event order: ``status`` → (``sources`` → ``status`` → ``delta``…) →
    ``complete``, with ``error`` in place of ``complete`` when generation fails.
    """
    started = time.perf_counter()
    yield ("status", {"step": "retrieving", "detail": _STATUS_RETRIEVING})

    workspace = await get_business_workspace(db)
    if workspace is None:
        # No workspace means no workspace_id to persist against, so this turn is
        # not recorded — there is nothing to continue from either.
        logger.info("business chat: no workspace serves the portal")
        for event in _fixed_answer_events(NO_PUBLISHED_CONTENT_ANSWER):
            yield event
        return

    # Read history before recording this question, otherwise the model would see
    # it twice.
    history = await _to_llm_history(db, workspace.id, user.id)
    await _persist(db, workspace.id, user.id, "user", question)

    try:
        retrieval = await business_search(db, question)
    except Exception:
        logger.exception("business chat: retrieval failed")
        yield ("error", {"message": _ERROR_MESSAGE})
        return

    if retrieval.is_empty:
        answer = (
            OUT_OF_SCOPE_ANSWER
            if retrieval.has_published_content
            else NO_PUBLISHED_CONTENT_ANSWER
        )
        message_id = await _persist(db, workspace.id, user.id, "assistant", answer)
        for event in _fixed_answer_events(answer, message_id):
            yield event
        return

    sources = [{"label": s.label, "page_no": s.page_no} for s in retrieval.sources]
    yield ("sources", {"sources": sources})
    yield ("status", {"step": "generating", "detail": _STATUS_GENERATING})

    # The catalogue rides along in the same prompt, so suggestions cost no
    # extra LLM call. An empty catalogue leaves the contract out entirely.
    packages = await _load_catalog(db)
    system_prompt = build_business_system_prompt(
        retrieval.context, build_catalog_digest(packages)
    )

    provider = get_llm_provider()
    recommendation_sentinel = RecommendationSentinelFilter()
    lead_sentinel = LeadSentinelFilter()
    parts: list[str] = []
    failed = False

    try:
        async for text in _stream_answer(provider, system_prompt, history, question):
            # Two independent filters, chained: each is responsible only for
            # not letting its own marker reach the screen. Chaining them is
            # safe even if the markers share a "[[" prefix, because the
            # second filter re-buffers whatever the first one lets through —
            # see the design spec for why this composes correctly.
            after_recommendation = recommendation_sentinel.feed(text)
            visible = lead_sentinel.feed(after_recommendation)
            if visible:
                parts.append(visible)
                yield ("delta", {"text": visible})
    except Exception:
        logger.exception("business chat: LLM streaming failed")
        failed = True

    reco_trailing, suggested_ids = recommendation_sentinel.finish()
    # Text released by the first filter at finish() has never been through
    # the second filter yet — it still needs to be checked and buffered.
    visible_trailing = lead_sentinel.feed(reco_trailing)
    lead_trailing, lead_draft = lead_sentinel.finish()
    trailing = visible_trailing + lead_trailing
    if trailing:
        parts.append(trailing)
        yield ("delta", {"text": trailing})

    answer = "".join(parts).strip()
    _log_llm_call(provider, system_prompt, question, answer, started)

    if failed or not answer:
        # Whatever streamed is already on screen, so keep it — but say the turn
        # did not finish rather than presenting a truncated answer as complete.
        if answer:
            await _persist(db, workspace.id, user.id, "assistant", answer, sources)
        yield ("error", {"message": _ERROR_MESSAGE})
        return

    # Suggestions are an addition, never a precondition: an id the model made
    # up is dropped here rather than looked up, and the answer stands either
    # way.
    cards = [to_card(p) for p in resolve_recommendations(suggested_ids, packages)]
    if cards:
        yield ("recommendations", {"packages": cards})

    # A lead proposal is ephemeral: shown once during this live stream only,
    # never persisted and never repeated in the complete/history payloads. If
    # the customer reloads before confirming, the draft is gone — they simply
    # ask again.
    if lead_draft is not None:
        lead_cards = [to_card(p) for p in resolve_recommendations(lead_draft.package_ids, packages)]
        yield ("lead_prompt", {"summary": lead_draft.summary, "packages": lead_cards})

    message_id = await _persist(
        db, workspace.id, user.id, "assistant", answer, sources, cards
    )
    yield (
        "complete",
        {
            "message_id": message_id,
            "answer": answer,
            "sources": sources,
            "recommendations": cards,
        },
    )


async def _load_catalog(db: AsyncSession):
    """The active catalogue, or nothing.

    Best-effort on purpose: the catalogue only enables suggestions, so a
    failure reading it must degrade to "no suggestions" rather than break a
    grounded answer the customer asked for.
    """
    try:
        return await get_active_packages(db)
    except Exception:
        logger.exception("business chat: failed to load the package catalogue")
        return []


async def _stream_answer(
    provider,
    system_prompt: str,
    history: list[LLMMessage],
    question: str,
) -> AsyncGenerator[str, None]:
    messages = [*history, LLMMessage(role="user", content=question)]
    async for chunk in provider.astream(
        messages,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        system_prompt=system_prompt,
        think=False,
    ):
        # Only "text" is forwarded. A "thinking" chunk can restate the retrieved
        # context, and a "function_call" chunk has no meaning on this surface.
        if chunk.type == "text" and chunk.text:
            yield chunk.text


def _log_llm_call(
    provider, system_prompt: str, question: str, answer: str, started: float
) -> None:
    """Log the call per .claude/rules/llm-integration.md.

    ``LLMProvider.astream`` surfaces no usage metadata, so character counts
    stand in for token counts rather than being invented.
    """
    logger.info(
        "Business chat LLM call",
        extra={
            "provider": type(provider).__name__,
            "llm_model": getattr(provider, "_model", None),
            "prompt_chars": len(system_prompt) + len(question),
            "completion_chars": len(answer),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        },
    )
