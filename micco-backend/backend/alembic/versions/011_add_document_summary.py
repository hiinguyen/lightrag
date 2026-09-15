"""add_document_summary — cache the approval summary on the document

Revision ID: 011_add_document_summary
Revises: 010_add_business_packages
Create Date: 2026-09-15

Adds documents.summary: the plain-text summary generated once, in the
background, right before the upload notification goes out to the approval
group chat.

Nullable with no default on purpose. A summary is best-effort — an
unsupported file type, an unreadable file, or an LLM outage must never block
the approval request — so NULL means "no summary available", which every
reader already has to handle. Existing rows stay NULL rather than being
backfilled: re-summarising the archive would cost one LLM call per historical
document to answer a question nobody asked.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "011_add_document_summary"
down_revision: Union[str, None] = "010_add_business_packages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DOCUMENTS_TABLE = "documents"
SUMMARY_COLUMN = "summary"


def upgrade() -> None:
    insp = inspect(op.get_bind())

    columns = {c["name"] for c in insp.get_columns(DOCUMENTS_TABLE)}
    if SUMMARY_COLUMN not in columns:
        op.add_column(
            DOCUMENTS_TABLE,
            sa.Column(SUMMARY_COLUMN, sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column(DOCUMENTS_TABLE, SUMMARY_COLUMN)
