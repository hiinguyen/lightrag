"""The n8n AI Agent reads one section of a pending document through this endpoint.

Without an index it lists the headings, so the agent can pick the section a
question is about; with an index it returns just that section's text. Same
shared X-Webhook-Secret auth and PENDING-only rule as agent-content.
"""
from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient

from app.core.config import settings
from app.models.document import DocumentStatus

SECTIONS_URL = "/api/v1/documents/{document_id}/agent-sections"
SECRET = "test-n8n-secret"

CONTRACT = (
    "Điều 1. Phạm vi áp dụng\n"
    "Hợp đồng áp dụng cho toàn bộ đơn hàng thuốc nổ công nghiệp.\n"
    "Điều 2. Thanh toán\n"
    "Bên A thanh toán trong vòng 30 ngày kể từ ngày nhận hàng.\n"
)


def _configure_secret(monkeypatch, secret: str | None = SECRET):
    monkeypatch.setattr(settings, "N8N_CALLBACK_SECRET", secret or "")


async def _staged_document(make_workspace, make_document, text: str = CONTRACT):
    workspace = await make_workspace()
    doc = await make_document(
        workspace_id=workspace.id,
        status=DocumentStatus.PENDING,
        approval_status="pending",
        original_filename="hop_dong.txt",
        filename="stored_hop_dong.txt",
        file_type="txt",
    )
    file_path = Path(settings.BASE_DIR) / "uploads" / doc.filename
    file_path.write_text(text, encoding="utf-8")
    return doc, file_path


async def test_agent_sections_rejects_missing_secret_header(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    doc, file_path = await _staged_document(make_workspace, make_document)

    try:
        response = await client.get(SECTIONS_URL.format(document_id=doc.id))
        assert response.status_code == 401
    finally:
        file_path.unlink(missing_ok=True)


async def test_agent_sections_404_for_unknown_document(client: AsyncClient, monkeypatch):
    _configure_secret(monkeypatch)

    response = await client.get(
        SECTIONS_URL.format(document_id=999999),
        headers={"X-Webhook-Secret": SECRET},
    )

    assert response.status_code == 404


async def test_agent_sections_409_when_document_is_no_longer_pending(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(
        workspace_id=workspace.id,
        status=DocumentStatus.INDEXED,
        approval_status="approved",
    )

    response = await client.get(
        SECTIONS_URL.format(document_id=doc.id),
        headers={"X-Webhook-Secret": SECRET},
    )

    assert response.status_code == 409


async def test_agent_sections_lists_headings_without_the_body_text(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    doc, file_path = await _staged_document(make_workspace, make_document)

    try:
        response = await client.get(
            SECTIONS_URL.format(document_id=doc.id),
            headers={"X-Webhook-Secret": SECRET},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert [s["heading"] for s in body["sections"]] == [
            "Điều 1. Phạm vi áp dụng",
            "Điều 2. Thanh toán",
        ]
        assert [s["index"] for s in body["sections"]] == [0, 1]
        # Listing must stay cheap: the agent asks for the body separately.
        assert "content" not in body["sections"][0]
        assert body["sections"][0]["chars"] > 0
    finally:
        file_path.unlink(missing_ok=True)


async def test_agent_sections_returns_one_section_by_index(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    doc, file_path = await _staged_document(make_workspace, make_document)

    try:
        response = await client.get(
            SECTIONS_URL.format(document_id=doc.id),
            params={"index": 1},
            headers={"X-Webhook-Secret": SECRET},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["index"] == 1
        assert body["heading"] == "Điều 2. Thanh toán"
        assert "30 ngày" in body["content"]
        assert "Phạm vi áp dụng" not in body["content"]
    finally:
        file_path.unlink(missing_ok=True)


async def test_agent_sections_404_for_an_index_past_the_end(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    doc, file_path = await _staged_document(make_workspace, make_document)

    try:
        response = await client.get(
            SECTIONS_URL.format(document_id=doc.id),
            params={"index": 9},
            headers={"X-Webhook-Secret": SECRET},
        )

        assert response.status_code == 404
    finally:
        file_path.unlink(missing_ok=True)


async def test_agent_sections_reports_unsupported_file_type(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(
        workspace_id=workspace.id,
        status=DocumentStatus.PENDING,
        approval_status="pending",
        original_filename="bang_gia.xlsx",
        filename="stored_sections_bang_gia.xlsx",
        file_type="xlsx",
    )
    file_path = Path(settings.BASE_DIR) / "uploads" / doc.filename
    file_path.write_bytes(b"not a real xlsx")

    try:
        response = await client.get(
            SECTIONS_URL.format(document_id=doc.id),
            headers={"X-Webhook-Secret": SECRET},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["supported"] is False
        assert body["count"] == 0
    finally:
        file_path.unlink(missing_ok=True)
