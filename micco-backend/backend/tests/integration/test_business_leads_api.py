"""POST /api/v1/business/leads — confirming a lead-handoff draft.

This is the only place a BusinessLead row is written; the chat stream only
proposes one (see test_business_lead_prompt_stream.py). These tests hold two
promises: the row snapshots the signed-in customer's own contact details, and
an id the model or the client made up cannot reach a lead as a real package.
"""
from __future__ import annotations

from httpx import AsyncClient

import app.api.business_leads as business_leads_module

LEADS_URL = "/api/v1/business/leads"


async def test_requires_authentication(client: AsyncClient):
    response = await client.post(LEADS_URL, json={"summary": "Cần tư vấn", "package_ids": []})

    assert response.status_code == 401


async def test_empty_summary_is_rejected(business_client: AsyncClient):
    response = await business_client.post(LEADS_URL, json={"summary": "", "package_ids": []})

    assert response.status_code == 422


async def test_whitespace_only_summary_is_rejected(business_client: AsyncClient):
    """min_length alone checks the raw value, so "   " would otherwise pass
    validation and get stored as "" once the endpoint strips it."""
    response = await business_client.post(LEADS_URL, json={"summary": "   ", "package_ids": []})

    assert response.status_code == 422


async def test_creates_a_lead_with_the_customers_own_contact_snapshot(
    business_client: AsyncClient, business_user
):
    response = await business_client.post(
        LEADS_URL,
        json={"summary": "Cần 200 tấn anfo, ngân sách khoảng 200 triệu", "package_ids": []},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["id"] > 0
    assert data["created_at"]


async def test_lead_snapshots_contact_details_from_the_current_user(
    business_client: AsyncClient, business_user, test_db
):
    from sqlalchemy import select

    from app.models.business_lead import BusinessLead

    await business_client.post(
        LEADS_URL, json={"summary": "Cần tư vấn hợp đồng", "package_ids": []}
    )

    result = await test_db.execute(select(BusinessLead))
    lead = result.scalars().first()

    assert lead.business_user_id == business_user.id
    assert lead.company_name == business_user.company_name
    assert lead.contact_phone == business_user.phone
    assert lead.contact_email == business_user.email
    assert lead.summary == "Cần tư vấn hợp đồng"


async def test_valid_package_ids_are_kept(business_client: AsyncClient, make_package, test_db):
    from sqlalchemy import select

    from app.models.business_lead import BusinessLead

    package = await make_package(name="Cung ứng thuốc nổ")

    await business_client.post(
        LEADS_URL, json={"summary": "Cần gói này", "package_ids": [package.id]}
    )

    result = await test_db.execute(select(BusinessLead))
    lead = result.scalars().first()

    assert lead.package_ids == [package.id]


async def test_hallucinated_or_inactive_package_ids_are_dropped(
    business_client: AsyncClient, make_package, test_db
):
    from sqlalchemy import select

    from app.models.business_lead import BusinessLead

    inactive = await make_package(name="Gói đã ngừng", is_active=False)

    await business_client.post(
        LEADS_URL, json={"summary": "Cần tư vấn", "package_ids": [9999, inactive.id]}
    )

    result = await test_db.execute(select(BusinessLead))
    lead = result.scalars().first()

    assert lead.package_ids == []


async def test_schedules_the_n8n_notification_with_the_new_lead_id(
    business_client: AsyncClient, monkeypatch
):
    calls: list[int] = []

    async def _recording_notifier(lead_id: int) -> None:
        calls.append(lead_id)

    monkeypatch.setattr(business_leads_module, "notify_lead_created", _recording_notifier)

    response = await business_client.post(
        LEADS_URL, json={"summary": "Cần tư vấn", "package_ids": []}
    )

    lead_id = response.json()["data"]["id"]
    assert calls == [lead_id]


async def test_unknown_fields_are_rejected(business_client: AsyncClient):
    response = await business_client.post(
        LEADS_URL, json={"summary": "Cần tư vấn", "package_ids": [], "status": "won"}
    )

    assert response.status_code == 422
