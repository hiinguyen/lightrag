"""resync knowledge_bases id sequence after explicit-id inserts

Revision ID: 013_resync_kb_id_sequence
Revises: 012_add_business_leads
Create Date: 2026-09-16

get_or_create_default_workspace() inserts the compat default workspace with an
explicit primary key (settings.COMPAT_DEFAULT_WORKSPACE_ID). Postgres does not
advance the identity sequence for an INSERT that supplies the id, so on any
database where that row was created this way the sequence still points at 1.
The next workspace created through the API then collides with it and fails with
"duplicate key value violates unique constraint knowledge_bases_pkey" — which
is what blocked creating the workspace for the B2B portal.

app.api_compat.utils now resyncs the sequence right after that insert, so new
databases stay correct. This migration repairs databases that already drifted.

Idempotent, and safe on a healthy database: the next value ends up MAX(id) + 1
either way.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013_resync_kb_id_sequence"
down_revision: Union[str, None] = "012_add_business_leads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "SELECT setval(pg_get_serial_sequence('knowledge_bases', 'id'), "
        "COALESCE((SELECT MAX(id) FROM knowledge_bases), 1))"
    )


def downgrade() -> None:
    # Nothing to undo: the sequence position is repair state, not schema, and
    # rewinding it would reintroduce the duplicate-key failure.
    pass
