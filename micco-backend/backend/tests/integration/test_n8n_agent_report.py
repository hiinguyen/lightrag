"""The n8n AI Agent posts its drafted answer here to get back a PDF to attach
to the reply email. Pure rendering — no LLM calls, no approval_status change.
"""
from __future__ import annotations

from httpx import AsyncClient

from app.core.config import settings

REPORT_URL = "/api/v1/documents/{document_id}/agent-report"
SECRET = "test-n8n-secret"


def _configure_secret(monkeypatch, secret: str | None = SECRET):
    monkeypatch.setattr(settings, "N8N_CALLBACK_SECRET", secret or "")


async def test_agent_report_rejects_missing_secret_header(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(workspace_id=workspace.id)

    response = await client.post(
        REPORT_URL.format(document_id=doc.id),
        json={"title": "Tóm tắt", "content_markdown": "Nội dung."},
    )

    assert response.status_code == 401


async def test_agent_report_rejects_empty_content_markdown(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(workspace_id=workspace.id)

    response = await client.post(
        REPORT_URL.format(document_id=doc.id),
        json={"title": "Tóm tắt", "content_markdown": ""},
        headers={"X-Webhook-Secret": SECRET},
    )

    assert response.status_code == 422


async def test_agent_report_rejects_oversized_content_markdown(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(workspace_id=workspace.id)

    response = await client.post(
        REPORT_URL.format(document_id=doc.id),
        json={"title": "Tóm tắt", "content_markdown": "a" * 100_001},
        headers={"X-Webhook-Secret": SECRET},
    )

    assert response.status_code == 422


async def test_agent_report_404_for_unknown_document(client: AsyncClient, monkeypatch):
    _configure_secret(monkeypatch)

    response = await client.post(
        REPORT_URL.format(document_id=999999),
        json={"title": "Tóm tắt", "content_markdown": "Nội dung."},
        headers={"X-Webhook-Secret": SECRET},
    )

    assert response.status_code == 404


async def test_agent_report_returns_a_pdf_attachment(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(workspace_id=workspace.id)

    response = await client.post(
        REPORT_URL.format(document_id=doc.id),
        json={"title": "Tóm tắt tài liệu", "content_markdown": "# Mục 1\n\nNội dung tóm tắt."},
        headers={"X-Webhook-Secret": SECRET},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
