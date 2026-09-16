"""add_business_leads — customer-confirmed requests to buy or sign a contract

Revision ID: 012_add_business_leads
Revises: 011_add_document_summary
Create Date: 2026-09-15

Adds business_leads: a lead is created only when a customer confirms the
[[LEAD:...]] chat sentinel (see app.services.business_lead_sentinel). Contact
fields are a snapshot, not a live reference, so a lead survives the customer's
profile changing later. No status column — leads are insert-only, kept for
audit; there is no dashboard or CRM tracking yet.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "012_add_business_leads"
down_revision: Union[str, None] = "011_add_document_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEADS_TABLE = "business_leads"


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if LEADS_TABLE not in insp.get_table_names():
        op.create_table(
            LEADS_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column(
                "business_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("company_name", sa.String(length=255), nullable=True),
            sa.Column("contact_phone", sa.String(length=20), nullable=True),
            sa.Column("contact_email", sa.String(length=255), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("package_ids", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table(LEADS_TABLE)
