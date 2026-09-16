"""Lead-handoff endpoint (/api/v1/business/leads).

The customer's confirmation step for the [[LEAD:...]] chat sentinel (see
app.services.business_lead_sentinel and app.services.business_chat): the chat
stream only ever proposes a draft through the lead_prompt SSE event, never
writes one. This is the only place a BusinessLead row is created.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.business_deps import get_current_business_user
from app.core.deps import get_db
from app.models.business_lead import BusinessLead
from app.models.user import User
from app.schemas.business import (
    BusinessEnvelope,
    BusinessLeadCreated,
    BusinessLeadCreateRequest,
)
from app.services.business_packages import get_active_packages, resolve_recommendations
from app.services.n8n_webhook import notify_lead_created

router = APIRouter(prefix="/business/leads", tags=["Business Portal"])


@router.post("", response_model=BusinessEnvelope[BusinessLeadCreated])
async def create_business_lead(
    req: BusinessLeadCreateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_business_user),
):
    """Record a customer-confirmed lead and notify sales.

    package_ids is re-validated against the active catalogue here, even
    though the chat stream already validated it once when it proposed the
    draft — the catalogue can change between the proposal and the customer's
    confirmation, and an id the client sent by hand must not be trusted.
    """
    packages = await get_active_packages(db)
    valid_ids = [p.id for p in resolve_recommendations(req.package_ids, packages)]

    lead = BusinessLead(
        business_user_id=current_user.id,
        company_name=current_user.company_name,
        contact_phone=current_user.phone,
        contact_email=current_user.email,
        summary=req.summary.strip(),
        package_ids=valid_ids,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)

    background_tasks.add_task(notify_lead_created, lead.id)

    return BusinessEnvelope(data=BusinessLeadCreated(id=lead.id, created_at=lead.created_at))
