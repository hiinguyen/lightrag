"""n8n AI Agent tool endpoints — email-reply flow for pending documents.

Independent of app.api.documents.approval_callback: these endpoints never
touch approval_status. They let an n8n AI Agent (1) read a pending
document's raw text and (2) render its generated answer as a PDF to attach
to the reply email. Authenticated the same way as approval-callback: a
shared secret in X-Webhook-Secret (see app.core.deps.verify_n8n_webhook_secret).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents import UPLOAD_DIR
from app.core.deps import get_db, verify_n8n_webhook_secret
from app.core.exceptions import ConflictError, NotFoundError
from app.models.document import Document, DocumentStatus
from app.models.user import User
from app.schemas.document import AgentReportRequest
from app.services.agent_pdf import render_markdown_to_pdf
from app.services.document_sections import split_into_sections
from app.services.document_text_extractor import extract_full_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["n8n-agent"])

AGENT_PENDING_LIMIT = 50


@router.get(
    "/agent/pending",
    dependencies=[Depends(verify_n8n_webhook_secret)],
)
async def list_agent_pending(db: AsyncSession = Depends(get_db)):
    """Documents still awaiting an approval decision, newest first.

    Two path segments on purpose: documents.py registers /{document_id}
    first, and a single-segment /agent-pending would be swallowed by it.
    An admin upload arrives pre-approved, so approval_status filters it out
    even though it is still PENDING processing.

    Reads one row past the cap to report `truncated`, so a backlog longer
    than the cap is visible to the group instead of silently dropping the
    oldest requests off the list.
    """
    rows = (
        await db.execute(
            select(Document, User)
            .outerjoin(User, Document.uploader_id == User.id)
            .where(
                Document.status == DocumentStatus.PENDING,
                Document.approval_status == "pending",
            )
            .order_by(Document.created_at.desc(), Document.id.desc())
            .limit(AGENT_PENDING_LIMIT + 1)
        )
    ).all()

    truncated = len(rows) > AGENT_PENDING_LIMIT
    rows = rows[:AGENT_PENDING_LIMIT]

    documents = [
        {
            "id": document.id,
            "filename": document.original_filename,
            "file_type": document.file_type,
            "file_size": document.file_size,
            "workspace_id": document.workspace_id,
            "department_id": document.department_id,
            "uploader": (
                {"name": uploader.name, "email": uploader.email} if uploader else None
            ),
            "created_at": document.created_at.isoformat() if document.created_at else None,
        }
        for document, uploader in rows
    ]

    logger.info(
        f"n8n agent/pending: served {len(documents)} document(s) awaiting approval, "
        f"truncated={truncated}"
    )

    return {"count": len(documents), "truncated": truncated, "documents": documents}


async def _load_pending_document(db: AsyncSession, document_id: int) -> Document:
    """Fetch a document the agent may still act on, or raise 404/409."""
    document = (
        await db.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if document is None:
        raise NotFoundError("Document", document_id)

    if document.status != DocumentStatus.PENDING:
        raise ConflictError("Document is no longer pending")

    return document


@router.get(
    "/{document_id}/agent-content",
    dependencies=[Depends(verify_n8n_webhook_secret)],
)
async def get_agent_content(document_id: int, db: AsyncSession = Depends(get_db)):
    """Raw text of a PENDING document, for the n8n AI Agent to reason over."""
    document = await _load_pending_document(db, document_id)

    file_path = UPLOAD_DIR / document.filename
    if not file_path.exists():
        raise NotFoundError("Document file", document_id)

    extracted = await extract_full_text(file_path, document.file_type)

    logger.info(
        f"n8n agent-content: served document {document.id} ({document.original_filename}), "
        f"supported={extracted.supported}, truncated={extracted.truncated}"
    )

    return {
        "id": document.id,
        "filename": document.original_filename,
        "file_type": document.file_type,
        "supported": extracted.supported,
        "content": extracted.content,
        "truncated": extracted.truncated,
        "message": None if extracted.supported else "Preview not supported for this file type",
    }


@router.get(
    "/{document_id}/agent-sections",
    dependencies=[Depends(verify_n8n_webhook_secret)],
)
async def get_agent_sections(
    document_id: int,
    index: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List a pending document's sections, or return one section's text.

    Without *index* this answers with headings only, so the agent can choose
    where a question belongs without paying for the whole file; with *index*
    it returns that section alone.
    """
    document = await _load_pending_document(db, document_id)

    file_path = UPLOAD_DIR / document.filename
    if not file_path.exists():
        raise NotFoundError("Document file", document_id)

    extracted = await extract_full_text(file_path, document.file_type)
    sections = split_into_sections(extracted.content or "") if extracted.supported else []

    if index is None:
        logger.info(
            f"n8n agent-sections: listed {len(sections)} section(s) of document {document_id}"
        )
        return {
            "id": document.id,
            "filename": document.original_filename,
            "supported": extracted.supported,
            "truncated": extracted.truncated,
            "count": len(sections),
            "sections": [
                {"index": position, "heading": section.heading, "chars": len(section.content)}
                for position, section in enumerate(sections)
            ],
        }

    if index < 0 or index >= len(sections):
        raise NotFoundError("Document section", index)

    section = sections[index]
    logger.info(f"n8n agent-sections: served section {index} of document {document_id}")
    return {
        "id": document.id,
        "index": index,
        "heading": section.heading,
        "content": section.content,
    }


@router.post(
    "/{document_id}/agent-report",
    dependencies=[Depends(verify_n8n_webhook_secret)],
)
async def create_agent_report(
    document_id: int,
    payload: AgentReportRequest,
    db: AsyncSession = Depends(get_db),
):
    """Render the AI Agent's drafted markdown answer as a PDF for email attachment."""
    document = (
        await db.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if document is None:
        raise NotFoundError("Document", document_id)

    pdf_bytes = await asyncio.to_thread(
        render_markdown_to_pdf, payload.title, payload.content_markdown
    )

    logger.info(
        f"n8n agent-report: rendered PDF report for document {document_id} "
        f"({document.original_filename})"
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="tai_lieu_{document_id}_tom_tat.pdf"'
        },
    )
