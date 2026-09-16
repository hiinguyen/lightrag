"""Outbound notification to the n8n approval-email workflow.

Called as a FastAPI BackgroundTasks target right after a document upload is
committed. Best-effort: any failure is logged and swallowed so it never
affects the upload response, and a missing N8N_WEBHOOK_URL makes the call a
no-op (n8n integration is optional).
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.core.config import settings
from app.services.document_summarizer import ensure_document_summary

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 5.0

# How long the approval request may wait on a summary. A provider that fails
# fast already degrades gracefully; this is the bound for one that hangs,
# which would otherwise hold the notification forever.
SUMMARY_TIMEOUT_SECONDS = 120.0


async def notify_document_uploaded(document_id: int) -> None:
    """Post a document.uploaded event to the configured n8n webhook."""
    if not settings.N8N_WEBHOOK_URL:
        logger.info(
            f"n8n webhook: N8N_WEBHOOK_URL not configured, skipping notify for document {document_id}"
        )
        return

    try:
        from sqlalchemy import select

        from app.core.database import async_session_maker
        from app.models.document import Document
        from app.models.user import User

        async with async_session_maker() as db:
            result = await db.execute(select(Document).where(Document.id == document_id))
            document = result.scalar_one_or_none()
            if document is None:
                logger.warning(f"n8n webhook: document {document_id} not found, skipping notify")
                return

            uploader = None
            if document.uploader_id:
                uploader_result = await db.execute(select(User).where(User.id == document.uploader_id))
                uploader = uploader_result.scalar_one_or_none()

            # Only documents that still need a decision are worth the LLM call;
            # a pre-approved upload goes straight to processing, unread.
            if document.approval_status == "pending":
                try:
                    await asyncio.wait_for(
                        ensure_document_summary(db, document),
                        timeout=SUMMARY_TIMEOUT_SECONDS,
                    )
                except Exception as e:
                    # The approval request must go out even with no summary:
                    # an LLM outage cannot be allowed to stall approvals.
                    logger.warning(
                        f"n8n webhook: summary unavailable for document {document_id}: {e}"
                    )

            payload = {
                "event": "document.uploaded",
                "document": {
                    "id": document.id,
                    "filename": document.original_filename,
                    "file_type": document.file_type,
                    "file_size": document.file_size,
                    "status": document.status.value if hasattr(document.status, "value") else document.status,
                    "workspace_id": document.workspace_id,
                    "department_id": document.department_id,
                    "visibility": document.visibility,
                    "approval_status": document.approval_status,
                    "created_at": document.created_at.isoformat() if document.created_at else None,
                    "summary": document.summary,
                },
                "uploader": {
                    "id": uploader.id,
                    "name": uploader.name,
                    "email": uploader.email,
                } if uploader else None,
            }

        logger.info(f"n8n webhook: notifying document.uploaded for document {document_id} -> {settings.N8N_WEBHOOK_URL}")

        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(settings.N8N_WEBHOOK_URL, json=payload)
            response.raise_for_status()

        logger.info(f"n8n webhook: document {document_id} notified successfully (status {response.status_code})")
    except Exception as e:
        logger.warning(f"n8n webhook call failed for document {document_id}: {e}")


async def notify_lead_created(lead_id: int) -> None:
    """Post a lead.created event to the configured n8n webhook.

    Posted to the same n8n instance/URL as notify_document_uploaded, as a
    different event type — discriminated by the "event" field. No new
    secret or URL.
    """
    if not settings.N8N_WEBHOOK_URL:
        logger.info(
            f"n8n webhook: N8N_WEBHOOK_URL not configured, skipping notify for lead {lead_id}"
        )
        return

    try:
        from sqlalchemy import select

        from app.core.database import async_session_maker
        from app.models.business_lead import BusinessLead
        from app.models.business_package import BusinessPackage

        async with async_session_maker() as db:
            result = await db.execute(select(BusinessLead).where(BusinessLead.id == lead_id))
            lead = result.scalar_one_or_none()
            if lead is None:
                logger.warning(f"n8n webhook: lead {lead_id} not found, skipping notify")
                return

            packages: list[dict] = []
            if lead.package_ids:
                # No is_active filter here, unlike resolve_recommendations: a lead is
                # a snapshot at confirmation time, so a package deactivated afterward
                # should still show up correctly in the sales notification.
                pkg_result = await db.execute(
                    select(BusinessPackage).where(BusinessPackage.id.in_(lead.package_ids))
                )
                packages = [{"id": p.id, "name": p.name} for p in pkg_result.scalars().all()]

            payload = {
                "event": "lead.created",
                "lead": {
                    "id": lead.id,
                    "company_name": lead.company_name,
                    "contact_phone": lead.contact_phone,
                    "contact_email": lead.contact_email,
                    "summary": lead.summary,
                    "packages": packages,
                    "created_at": lead.created_at.isoformat() if lead.created_at else None,
                },
            }

        logger.info(f"n8n webhook: notifying lead.created for lead {lead_id} -> {settings.N8N_WEBHOOK_URL}")

        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(settings.N8N_WEBHOOK_URL, json=payload)
            response.raise_for_status()

        logger.info(f"n8n webhook: lead {lead_id} notified successfully (status {response.status_code})")
    except Exception as e:
        logger.warning(f"n8n webhook call failed for lead {lead_id}: {e}")
