"""Portal chat endpoints (/api/v1/business/chat/...).

The second half of the externally reachable surface; see ``app.api.business``
for the first. Every endpoint here sits behind ``get_current_business_user``,
so an internal token — including the ``dev-skip`` bypass — cannot reach it.

This layer stays thin on purpose: orchestration lives in
``app.services.business_chat`` so the event order can be tested without going
through SSE.

SSE events emitted by POST /stream:
  - status:   {"step": str, "detail": str}
  - sources:  {"sources": [{"label": str, "page_no": int}]}
  - delta:    {"text": str}
  - recommendations: {"packages": [BusinessPackageCard, ...]}
  - lead_prompt: {"summary": str, "packages": [BusinessPackageCard, ...]}
  - complete: {"message_id": str, "answer": str, "sources": [...]}
  - error:    {"message": str}
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

# Pure formatting helpers, shared with the internal streaming chat so both
# surfaces frame SSE and heartbeat identically.
from app.api.chat_agent import format_sse_event, sse_with_heartbeat
from app.core.business_deps import get_current_business_user
from app.core.deps import get_db
from app.models.user import User
from app.schemas.business import (
    BusinessChatCleared,
    BusinessChatHistoryData,
    BusinessChatMessage,
    BusinessChatRequest,
    BusinessEnvelope,
)
from app.services.business_chat import (
    clear_business_history,
    load_business_messages,
    stream_business_chat,
)
from app.services.business_rag import get_business_workspace

router = APIRouter(prefix="/business/chat", tags=["Business Portal"])

_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


@router.post("/stream")
async def business_chat_stream(
    req: BusinessChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_business_user),
):
    """Stream an answer grounded in published business documents."""

    async def _frames():
        async for event, payload in stream_business_chat(
            db, current_user, req.message.strip()
        ):
            yield format_sse_event(event, payload)

    return StreamingResponse(
        sse_with_heartbeat(_frames()),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )


@router.get("/history", response_model=BusinessEnvelope[BusinessChatHistoryData])
async def get_business_chat_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_business_user),
):
    """The signed-in customer's own conversation.

    Returns an empty conversation rather than a 404 when no workspace serves
    the portal — there is simply nothing recorded yet.
    """
    workspace = await get_business_workspace(db)
    if workspace is None:
        return BusinessEnvelope(data=BusinessChatHistoryData())

    rows = await load_business_messages(db, workspace.id, current_user.id)
    messages = [
        BusinessChatMessage(
            message_id=row.message_id,
            role=row.role,
            content=row.content,
            # Validated through BusinessChatSource, so a stored row can only
            # ever hand back a label and a page number.
            sources=row.sources or [],
            # Same for the cards: re-validated on the way out, so the suggestion
            # cards survive a reload without widening what a row can return.
            recommendations=row.recommended_packages or [],
            created_at=row.created_at,
        )
        for row in rows
    ]
    return BusinessEnvelope(
        data=BusinessChatHistoryData(messages=messages, total=len(messages))
    )


@router.delete("/history", response_model=BusinessEnvelope[BusinessChatCleared])
async def delete_business_chat_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_business_user),
):
    """Clear the signed-in customer's own conversation."""
    workspace = await get_business_workspace(db)
    if workspace is None:
        return BusinessEnvelope(data=BusinessChatCleared(deleted=0))

    deleted = await clear_business_history(db, workspace.id, current_user.id)
    return BusinessEnvelope(data=BusinessChatCleared(deleted=deleted))
