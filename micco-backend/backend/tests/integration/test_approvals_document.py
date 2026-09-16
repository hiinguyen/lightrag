"""Regression test for the approve-document flow after the DRY refactor.

approve_document (app/api_compat/approvals.py) used to inline the
workspace-resolution + background-ingest kickoff; that logic now lives in
app.api.documents._finalize_approval_and_ingest, shared with the n8n
approval-callback endpoint. This confirms the in-app approve endpoint still
works end to end through the shared helper.
"""
from __future__ import annotations

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.documents as documents_module
from app.core.deps import get_db
from app.models.document import DocumentStatus

APPROVE_URL = "/api/approvals/documents/{doc_id}/approve"


@pytest_asyncio.fixture
async def approvals_client(test_db: AsyncSession) -> AsyncClient:
    from app.api_compat.approvals import router as approvals_router

    application = FastAPI()
    application.include_router(approvals_router)

    async def _override_get_db():
        yield test_db

    application.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as async_client:
        yield async_client


class _RecordingIngest:
    def __init__(self):
        self.calls: list[tuple[int, str, int]] = []

    async def __call__(self, document_id: int, file_path: str, workspace_id: int) -> None:
        self.calls.append((document_id, file_path, workspace_id))


async def test_admin_approve_document_ingests_via_shared_helper(
    approvals_client: AsyncClient,
    admin_user,
    make_workspace,
    make_document,
    monkeypatch,
    test_db,
):
    recorder = _RecordingIngest()
    monkeypatch.setattr(documents_module, "process_document_background", recorder)

    workspace = await make_workspace(name="KB Approvals Test")
    doc = await make_document(
        workspace_id=workspace.id,
        status=DocumentStatus.PENDING,
        approval_status="pending",
        visibility="internal",
    )

    from app.core.security import create_access_token

    token = create_access_token(data={"sub": admin_user.id})
    approvals_client.headers.update({"Authorization": f"Bearer {token}"})

    response = await approvals_client.post(APPROVE_URL.format(doc_id=doc.id))

    assert response.status_code == 200
    body = response.json()
    assert body["processing_started"] is True

    assert len(recorder.calls) == 1
    ingested_document_id, _file_path, _workspace_id = recorder.calls[0]
    assert ingested_document_id == doc.id

    await test_db.refresh(doc)
    assert doc.approval_status == "approved"
    assert doc.status == DocumentStatus.PROCESSING


async def test_approve_after_failed_ingest_restarts_processing(
    approvals_client: AsyncClient,
    admin_user,
    make_workspace,
    make_document,
    monkeypatch,
    test_db,
):
    """A crashed ingestion is retried by approving the document again.

    app.services.document_failure hands a FAILED document back to the approval
    queue, so the approve endpoint must accept FAILED as a starting state and
    clear the stale error instead of silently doing nothing.
    """
    recorder = _RecordingIngest()
    monkeypatch.setattr(documents_module, "process_document_background", recorder)

    workspace = await make_workspace(name="KB Retry Test")
    doc = await make_document(
        workspace_id=workspace.id,
        status=DocumentStatus.FAILED,
        approval_status="pending",
        visibility="internal",
        error_message="Hết bộ nhớ GPU khi xử lý tài liệu.",
    )

    from app.core.security import create_access_token

    token = create_access_token(data={"sub": admin_user.id})
    approvals_client.headers.update({"Authorization": f"Bearer {token}"})

    response = await approvals_client.post(APPROVE_URL.format(doc_id=doc.id))

    assert response.status_code == 200
    assert response.json()["processing_started"] is True
    assert len(recorder.calls) == 1

    await test_db.refresh(doc)
    assert doc.approval_status == "approved"
    assert doc.status == DocumentStatus.PROCESSING
    assert doc.error_message is None
