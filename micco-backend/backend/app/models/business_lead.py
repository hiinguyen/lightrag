"""
BusinessLead model — a customer-confirmed request to buy or sign a contract.

Written only by POST /api/v1/business/leads (app.api.business_leads), never by
the chat stream itself: the stream only proposes a draft (see
app.services.business_lead_sentinel), and a draft becomes a row solely because
the customer clicked confirm. Contact fields are a snapshot of the customer's
profile at that moment, not a live join to `users` — a lead must keep reading
back the same contact details even if the customer's profile changes later.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BusinessLead(Base):
    __tablename__ = "business_leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    business_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Snapshot of the customer's contact details at the moment the lead was
    # confirmed — never re-read from `users` later.
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)

    # The model's tóm tắt of the customer's need, including budget if the
    # customer mentioned one. Free text on purpose — see the design spec for
    # why this is not split into a separate budget column.
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    # Package ids the customer was discussing, already re-validated against
    # the active catalogue by the endpoint that writes this row. May be empty.
    package_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
