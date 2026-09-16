"""Single place that decides what happens to a document when ingestion fails.

Ingestion can die in several places (NexusRAG, the legacy RAG service, the
background-task wrapper, the stale-document sweep at startup). All of them
funnel through `mark_document_failed` so a failure always looks the same to
the UI: status FAILED + a human-readable error + the document handed back to
the approval queue, where one approve click restarts ingestion.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus

logger = logging.getLogger(__name__)

ERROR_MESSAGE_MAX_LENGTH = 500

# Stage the document is sent back to. A public document needs the organisation
# approval as its last step before ingestion, everything else the department
# one — so in both cases exactly one approve click retries the ingestion
# instead of replaying the whole approval chain.
APPROVAL_STAGE_ORG = "pending_org"
APPROVAL_STAGE_DEPT = "pending"


def retry_approval_stage(document: Document) -> str:
    """Approval stage a failed document goes back to."""
    return (
        APPROVAL_STAGE_ORG
        if (document.visibility or "internal") == "public"
        else APPROVAL_STAGE_DEPT
    )


def describe_failure(error: BaseException | str) -> str:
    """Turn a raw exception into a message an approver can act on."""
    raw = str(error).strip() or "Lỗi không xác định"
    lowered = raw.lower()

    if "out of memory" in lowered or ("cuda" in lowered and "memory" in lowered):
        hint = "Hết bộ nhớ GPU khi xử lý tài liệu. Vui lòng thử lại khi máy chủ rảnh."
    elif "timeout" in lowered or "timed out" in lowered:
        hint = "Quá thời gian xử lý cho phép."
    elif "no such file" in lowered or "not found on disk" in lowered:
        hint = "Không tìm thấy tệp tài liệu trên máy chủ."
    else:
        hint = "Xử lý tài liệu thất bại."

    return f"{hint} (Chi tiết: {raw})"[:ERROR_MESSAGE_MAX_LENGTH]


async def mark_document_failed(
    db: AsyncSession,
    document: Document,
    error: BaseException | str,
) -> None:
    """Flag the document as failed and put it back in the approval queue."""
    document.status = DocumentStatus.FAILED
    document.error_message = describe_failure(error)
    document.approval_status = retry_approval_stage(document)
    await db.commit()
    logger.warning(
        "Document %s failed ingestion, returned to approval stage '%s': %s",
        document.id,
        document.approval_status,
        document.error_message,
    )
