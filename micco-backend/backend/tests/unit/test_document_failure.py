"""Unit tests for the shared ingestion-failure policy.

See app/services/document_failure.py: every failed ingestion must surface a
readable error AND hand the document back to the approval queue, so approving
it again is the retry.
"""
from __future__ import annotations

import pytest

from app.models.document import Document, DocumentStatus
from app.services.document_failure import (
    ERROR_MESSAGE_MAX_LENGTH,
    describe_failure,
    mark_document_failed,
    retry_approval_stage,
)

CUDA_OOM = (
    "CUDA out of memory. Tried to allocate 16.00 MiB. GPU 0 has a total "
    "capacity of 7.57 GiB of which 32.81 MiB is free."
)


def _document(**columns) -> Document:
    defaults = dict(
        workspace_id=1,
        filename="stored.pdf",
        original_filename="Bao cao.pdf",
        file_type="pdf",
        file_size=1024,
        status=DocumentStatus.PROCESSING,
        approval_status="approved",
        visibility="department",
    )
    return Document(**{**defaults, **columns})


def test_describe_failure_cuda_oom_returns_readable_hint_and_detail():
    # Arrange / Act
    message = describe_failure(RuntimeError(CUDA_OOM))

    # Assert
    assert "Hết bộ nhớ GPU" in message
    assert "CUDA out of memory" in message


def test_describe_failure_timeout_returns_timeout_hint():
    assert "Quá thời gian xử lý" in describe_failure("Processing timeout (10min)")


def test_describe_failure_missing_file_returns_missing_file_hint():
    """Phrasing observed in a real run: the loader raises "File not found: <path>"."""
    message = describe_failure(FileNotFoundError("File not found: /uploads/abc.md"))

    assert "Không tìm thấy tệp tài liệu" in message


def test_describe_failure_unknown_error_returns_generic_hint():
    assert "Xử lý tài liệu thất bại" in describe_failure(ValueError("weird crash"))


def test_describe_failure_long_error_is_truncated_to_column_width():
    assert len(describe_failure("x" * 5000)) == ERROR_MESSAGE_MAX_LENGTH


def test_describe_failure_empty_error_returns_placeholder_detail():
    assert "Lỗi không xác định" in describe_failure("   ")


def test_retry_approval_stage_department_document_returns_department_stage():
    assert retry_approval_stage(_document(visibility="department")) == "pending"


def test_retry_approval_stage_public_document_returns_org_stage():
    assert retry_approval_stage(_document(visibility="public")) == "pending_org"


@pytest.mark.asyncio
async def test_mark_document_failed_sets_failed_status_and_requeues_for_approval(test_db):
    # Arrange
    from app.models.knowledge_base import KnowledgeBase

    workspace = KnowledgeBase(name="KB Failure Test")
    test_db.add(workspace)
    await test_db.commit()
    await test_db.refresh(workspace)

    document = _document(workspace_id=workspace.id)
    test_db.add(document)
    await test_db.commit()

    # Act
    await mark_document_failed(test_db, document, RuntimeError(CUDA_OOM))

    # Assert
    await test_db.refresh(document)
    assert document.status == DocumentStatus.FAILED
    assert document.approval_status == "pending"
    assert "Hết bộ nhớ GPU" in document.error_message
