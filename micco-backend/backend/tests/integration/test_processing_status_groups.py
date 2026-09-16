"""The "Tiến trình xử lý" tabs must keep the four document states apart.

GET /api/documents/processing-status backs one tab per state. "Chờ phê duyệt"
used to be lumped in with "Đang xử lý", which made a document waiting on an
approver look like one the pipeline was working on, and a failed document had
no tab of its own at all.
"""
from __future__ import annotations

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.deps import get_db
from app.models.document import DocumentStatus

STATUS_URL = "/api/documents/processing-status"


@pytest_asyncio.fixture
async def documents_client(test_db) -> AsyncClient:
    from app.api_compat.documents import router as documents_router

    application = FastAPI()
    application.include_router(documents_router)

    async def _override_get_db():
        yield test_db

    application.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as async_client:
        yield async_client


@pytest_asyncio.fixture
async def one_document_per_state(make_workspace, make_document, admin_user):
    """One document in each state an approver can be shown."""
    workspace = await make_workspace(name="KB Status Groups")

    async def _doc(status, **columns):
        return await make_document(
            workspace_id=workspace.id,
            status=status,
            uploader_id=admin_user.id,
            **columns,
        )

    return {
        "pending": await _doc(DocumentStatus.PENDING, approval_status="pending"),
        "processing": await _doc(DocumentStatus.INDEXING, approval_status="approved"),
        "failed": await _doc(
            DocumentStatus.FAILED,
            approval_status="pending",
            error_message="Hết bộ nhớ GPU khi xử lý tài liệu.",
        ),
        "indexed": await _doc(DocumentStatus.INDEXED, approval_status="approved"),
    }


def _authorise(client: AsyncClient, user) -> None:
    from app.core.security import create_access_token

    client.headers.update(
        {"Authorization": f"Bearer {create_access_token(data={'sub': user.id})}"}
    )


async def test_each_group_returns_only_its_own_documents(
    documents_client: AsyncClient, admin_user, one_document_per_state
):
    _authorise(documents_client, admin_user)

    for group, document in one_document_per_state.items():
        response = await documents_client.get(STATUS_URL, params={"filter": group})

        assert response.status_code == 200, group
        returned_ids = [item["id"] for item in response.json()["items"]]
        assert returned_ids == [document.id], group


async def test_counts_report_every_group_for_the_tab_badges(
    documents_client: AsyncClient, admin_user, one_document_per_state
):
    _authorise(documents_client, admin_user)

    counts = (await documents_client.get(STATUS_URL)).json()["counts"]

    assert counts["pending"] == 1
    assert counts["processing"] == 1
    assert counts["failed"] == 1
    assert counts["indexed"] == 1
    assert counts["all"] == 4


async def test_failed_document_awaiting_reapproval_stays_in_the_failed_group(
    documents_client: AsyncClient, admin_user, one_document_per_state
):
    """A crashed document is back in the approval queue but must NOT read as
    "chờ phê duyệt" — the UI needs to see it failed, plus why."""
    _authorise(documents_client, admin_user)

    failed_items = (
        await documents_client.get(STATUS_URL, params={"filter": "failed"})
    ).json()["items"]
    pending_ids = [
        item["id"]
        for item in (
            await documents_client.get(STATUS_URL, params={"filter": "pending"})
        ).json()["items"]
    ]

    assert len(failed_items) == 1
    assert failed_items[0]["approval_status"] == "pending"
    assert "Hết bộ nhớ GPU" in failed_items[0]["error_message"]
    assert one_document_per_state["failed"].id not in pending_ids
