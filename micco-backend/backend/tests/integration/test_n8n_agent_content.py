"""The n8n AI Agent reads a pending document's raw text through this endpoint.

Independent of approval-callback: never touches approval_status. Auth is the
same shared X-Webhook-Secret as approval-callback (app.core.deps).
"""
from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient

from app.core.config import settings
from app.models.document import DocumentStatus

CONTENT_URL = "/api/v1/documents/{document_id}/agent-content"
SECRET = "test-n8n-secret"


def _configure_secret(monkeypatch, secret: str | None = SECRET):
    monkeypatch.setattr(settings, "N8N_CALLBACK_SECRET", secret or "")


async def test_agent_content_rejects_missing_secret_header(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(workspace_id=workspace.id, status=DocumentStatus.PENDING)

    response = await client.get(CONTENT_URL.format(document_id=doc.id))

    assert response.status_code == 401


async def test_agent_content_rejects_wrong_secret(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(workspace_id=workspace.id, status=DocumentStatus.PENDING)

    response = await client.get(
        CONTENT_URL.format(document_id=doc.id),
        headers={"X-Webhook-Secret": "not-the-secret"},
    )

    assert response.status_code == 401


async def test_agent_content_404_for_unknown_document(client: AsyncClient, monkeypatch):
    _configure_secret(monkeypatch)

    response = await client.get(
        CONTENT_URL.format(document_id=999999),
        headers={"X-Webhook-Secret": SECRET},
    )

    assert response.status_code == 404


async def test_agent_content_409_when_document_is_no_longer_pending(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(
        workspace_id=workspace.id, status=DocumentStatus.INDEXED, approval_status="approved"
    )

    response = await client.get(
        CONTENT_URL.format(document_id=doc.id),
        headers={"X-Webhook-Secret": SECRET},
    )

    assert response.status_code == 409


async def test_agent_content_returns_extracted_text_for_pending_txt_document(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(
        workspace_id=workspace.id,
        status=DocumentStatus.PENDING,
        approval_status="pending",
        original_filename="ghi_chu.txt",
        filename="stored_ghi_chu.txt",
        file_type="txt",
    )
    file_path = Path(settings.BASE_DIR) / "uploads" / doc.filename
    file_path.write_text("Nội dung chờ duyệt.", encoding="utf-8")

    try:
        response = await client.get(
            CONTENT_URL.format(document_id=doc.id),
            headers={"X-Webhook-Secret": SECRET},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["supported"] is True
        assert body["content"] == "Nội dung chờ duyệt."
        assert body["truncated"] is False
    finally:
        file_path.unlink(missing_ok=True)


async def test_agent_content_reports_unsupported_file_type(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(
        workspace_id=workspace.id,
        status=DocumentStatus.PENDING,
        approval_status="pending",
        original_filename="bang_gia.xlsx",
        filename="stored_bang_gia.xlsx",
        file_type="xlsx",
    )
    file_path = Path(settings.BASE_DIR) / "uploads" / doc.filename
    file_path.write_bytes(b"not a real xlsx")

    try:
        response = await client.get(
            CONTENT_URL.format(document_id=doc.id),
            headers={"X-Webhook-Secret": SECRET},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["supported"] is False
        assert body["content"] is None
    finally:
        file_path.unlink(missing_ok=True)
