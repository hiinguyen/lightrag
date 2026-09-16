"""Workspace nào giữ tài liệu sau khi duyệt.

Luồng nội bộ cố ý "thăng" tài liệu khi duyệt: từ workspace cá nhân lên
workspace phòng ban (hoặc mặc định). Nhưng workspace phục vụ cổng doanh nghiệp
là đích đến do Admin chọn, không phải nơi tạm — kéo tài liệu ra khỏi đó sẽ làm
bước publish sau này fail với "Tài liệu không nằm trong workspace doanh nghiệp".
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api_compat.utils import get_or_create_default_workspace

from app.api.documents import _finalize_approval_and_ingest
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase


class _NoopBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append((func, args, kwargs))


async def _make_workspace(db, name: str, audience: str, ws_id: int | None = None) -> KnowledgeBase:
    ws = KnowledgeBase(name=name, visibility="public", audience=audience)
    if ws_id is not None:
        ws.id = ws_id
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws


async def _make_pending_doc(db, workspace_id: int) -> Document:
    doc = Document(
        workspace_id=workspace_id,
        filename="f.pdf",
        original_filename="Báo giá.pdf",
        file_type="pdf",
        file_size=10,
        status=DocumentStatus.PENDING,
        approval_status="pending",
        visibility="private",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


@pytest.mark.asyncio
async def test_approval_keeps_document_in_business_workspace(test_db):
    # Workspace mặc định phải tồn tại và KHÁC workspace doanh nghiệp, nếu không
    # get_or_create_default_workspace() sẽ vô tình trả về chính nó.
    default_ws = await get_or_create_default_workspace(test_db)
    business_ws = await _make_workspace(test_db, "Tài liệu công bố", "business")
    assert business_ws.id != default_ws.id
    doc = await _make_pending_doc(test_db, business_ws.id)

    target = await _finalize_approval_and_ingest(test_db, doc, _NoopBackgroundTasks())

    assert target is not None
    assert target.id == business_ws.id
    refreshed = (
        await test_db.execute(select(Document).where(Document.id == doc.id))
    ).scalar_one()
    assert refreshed.workspace_id == business_ws.id
    assert refreshed.approval_status == "approved"


@pytest.mark.asyncio
async def test_approval_still_promotes_document_out_of_internal_workspace(test_db):
    default_ws = await get_or_create_default_workspace(test_db)
    internal_ws = await _make_workspace(test_db, "Workspace cá nhân", "internal")
    assert internal_ws.id != default_ws.id
    doc = await _make_pending_doc(test_db, internal_ws.id)

    target = await _finalize_approval_and_ingest(test_db, doc, _NoopBackgroundTasks())

    # Không có department_id -> rơi về workspace mặc định, đúng hành vi cũ.
    assert target is not None
    assert target.id == default_ws.id
