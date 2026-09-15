"""The n8n AI Agent lists documents awaiting approval through this endpoint.

Same shared X-Webhook-Secret auth as the other agent tool endpoints. "Awaiting
approval" means a document nobody has decided on yet: an admin upload is
pre-approved on arrival and must not show up as something to decide.
"""
from __future__ import annotations

from datetime import datetime

from httpx import AsyncClient

from app.core.config import settings
from app.models.document import DocumentStatus

PENDING_URL = "/api/v1/documents/agent/pending"
SECRET = "test-n8n-secret"


def _configure_secret(monkeypatch, secret: str | None = SECRET):
    monkeypatch.setattr(settings, "N8N_CALLBACK_SECRET", secret or "")


async def _make_awaiting(make_document, workspace_id: int, **columns):
    return await make_document(
        workspace_id=workspace_id,
        status=DocumentStatus.PENDING,
        approval_status="pending",
        **columns,
    )


async def test_agent_pending_rejects_missing_secret_header(
    client: AsyncClient, monkeypatch
):
    _configure_secret(monkeypatch)

    response = await client.get(PENDING_URL)

    assert response.status_code == 401


async def test_agent_pending_rejects_wrong_secret(client: AsyncClient, monkeypatch):
    _configure_secret(monkeypatch)

    response = await client.get(
        PENDING_URL, headers={"X-Webhook-Secret": "not-the-secret"}
    )

    assert response.status_code == 401


async def test_agent_pending_rejects_when_secret_is_not_configured(
    client: AsyncClient, monkeypatch
):
    _configure_secret(monkeypatch, secret=None)

    response = await client.get(PENDING_URL, headers={"X-Webhook-Secret": SECRET})

    assert response.status_code == 401


async def test_agent_pending_returns_empty_list_when_nothing_awaits_approval(
    client: AsyncClient, monkeypatch
):
    _configure_secret(monkeypatch)

    response = await client.get(PENDING_URL, headers={"X-Webhook-Secret": SECRET})

    assert response.status_code == 200
    assert response.json() == {"count": 0, "truncated": False, "documents": []}


async def test_agent_pending_returns_document_metadata_the_agent_needs(
    client: AsyncClient, make_workspace, make_document, make_user, monkeypatch
):
    _configure_secret(monkeypatch)
    uploader = await make_user(email="uploader@example.test", name="Nguyễn Văn A")
    workspace = await make_workspace()
    doc = await _make_awaiting(
        make_document,
        workspace.id,
        original_filename="0703C.pdf",
        file_type="pdf",
        uploader_id=uploader.id,
    )

    response = await client.get(PENDING_URL, headers={"X-Webhook-Secret": SECRET})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    listed = body["documents"][0]
    assert listed["id"] == doc.id
    assert listed["filename"] == "0703C.pdf"
    assert listed["file_type"] == "pdf"
    assert listed["file_size"] == doc.file_size
    assert listed["workspace_id"] == workspace.id
    assert listed["uploader"] == {
        "name": "Nguyễn Văn A",
        "email": "uploader@example.test",
    }
    assert listed["created_at"] is not None


async def test_agent_pending_reports_no_uploader_when_the_account_is_gone(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    await _make_awaiting(make_document, workspace.id, uploader_id=None)

    response = await client.get(PENDING_URL, headers={"X-Webhook-Secret": SECRET})

    assert response.status_code == 200
    assert response.json()["documents"][0]["uploader"] is None


async def test_agent_pending_excludes_documents_already_decided_on(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    awaiting = await _make_awaiting(make_document, workspace.id)
    await make_document(
        workspace_id=workspace.id,
        status=DocumentStatus.INDEXED,
        approval_status="approved",
    )
    await make_document(
        workspace_id=workspace.id,
        status=DocumentStatus.REJECTED,
        approval_status="rejected",
    )
    # Admin uploads land pre-approved: pending processing, not pending a decision.
    await make_document(
        workspace_id=workspace.id,
        status=DocumentStatus.PENDING,
        approval_status="approved",
    )

    response = await client.get(PENDING_URL, headers={"X-Webhook-Secret": SECRET})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert [d["id"] for d in body["documents"]] == [awaiting.id]


async def test_agent_pending_lists_newest_first(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    older = await _make_awaiting(
        make_document, workspace.id, created_at=datetime(2026, 9, 1, 8, 0, 0)
    )
    newer = await _make_awaiting(
        make_document, workspace.id, created_at=datetime(2026, 9, 14, 8, 0, 0)
    )

    response = await client.get(PENDING_URL, headers={"X-Webhook-Secret": SECRET})

    assert [d["id"] for d in response.json()["documents"]] == [newer.id, older.id]


async def test_agent_pending_caps_how_many_documents_it_returns(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    from app.api.n8n_agent import AGENT_PENDING_LIMIT

    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    for _ in range(AGENT_PENDING_LIMIT + 3):
        await _make_awaiting(make_document, workspace.id)

    response = await client.get(PENDING_URL, headers={"X-Webhook-Secret": SECRET})

    body = response.json()
    assert body["count"] == AGENT_PENDING_LIMIT
    assert len(body["documents"]) == AGENT_PENDING_LIMIT
    # Silence here would hide an unbounded backlog from the group chat.
    assert body["truncated"] is True


async def test_agent_pending_is_not_truncated_when_everything_fits(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    await _make_awaiting(make_document, workspace.id)

    response = await client.get(PENDING_URL, headers={"X-Webhook-Secret": SECRET})

    assert response.json()["truncated"] is False
