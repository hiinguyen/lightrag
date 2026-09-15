# Business Lead Handoff (Phase 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a B2B portal customer confirm sending a purchase/contract request ("lead") straight from the chat, so it reaches Micco sales through the existing n8n Telegram notification channel.

**Architecture:** The chat LLM ends its answer with a `[[LEAD: id1,id2|tóm tắt nhu cầu]]` sentinel when it detects clear purchase/contract intent. A new `LeadSentinelFilter` strips it from the streamed text (mirroring the existing `RecommendationSentinelFilter`) and the backend emits an SSE `lead_prompt` event carrying a draft — nothing is persisted yet. The customer confirms in the UI, which calls `POST /api/v1/business/leads`; that endpoint writes a `BusinessLead` row and schedules `notify_lead_created` as a background task, which posts a `lead.created` event to the same `N8N_WEBHOOK_URL` already used for document uploads.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (backend, `micco-backend/backend`), React 19 + Vite plain JSX (frontend, `micco-frontend`), pytest + pytest-asyncio + httpx `AsyncClient` for tests.

**Spec:** `docs/superpowers/specs/2026-09-15-business-lead-handoff-design.md`

## Global Constraints

- No new secrets or config: reuse `N8N_WEBHOOK_URL` (`app/core/config.py:127`), discriminate by a `"event"` field in the JSON payload.
- No `BusinessLead` status/dashboard/CRM tracking — insert-only, kept for audit.
- No `budget_note` column — budget (if the customer mentioned one) lives inside `summary`, a single free-text field.
- `lead_prompt` is never persisted to `ChatMessage` and does not survive a page reload — this is intentional, not a gap.
- Response envelope for `/business/leads` is `{"data": ..., "meta": {}}` per `.claude/rules/api-design.md`, matching every other `/business/*` endpoint.
- Every new/changed Python module keeps the project's existing docstring style (why, not what) and the existing sentinel fail-closed philosophy: a malformed `[[LEAD:...]]` must degrade to "no lead", never to a half-parsed one.

---

## Task 1: `BusinessLead` model + migration

**Files:**
- Create: `micco-backend/backend/app/models/business_lead.py`
- Modify: `micco-backend/backend/app/models/__init__.py`
- Create: `micco-backend/backend/alembic/versions/012_add_business_leads.py`

**Interfaces:**
- Produces: `app.models.business_lead.BusinessLead` — SQLAlchemy model, table `business_leads`, columns `id`, `business_user_id`, `company_name`, `contact_phone`, `contact_email`, `summary`, `package_ids` (JSON list of int), `created_at`. Later tasks construct rows with `BusinessLead(business_user_id=..., company_name=..., contact_phone=..., contact_email=..., summary=..., package_ids=...)`.

This is a schema task with no standalone behavior to unit test — its correctness is proven by Task 6's integration tests, which insert and read back a row through the real test database. Skip the red/green cycle here; instead verify the migration applies cleanly.

- [ ] **Step 1: Write the model**

`micco-backend/backend/app/models/business_lead.py`:

```python
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
```

- [ ] **Step 2: Register the model**

Modify `micco-backend/backend/app/models/__init__.py` — add the import and `__all__` entry, following the existing `BusinessPackage` line:

```python
from app.models.business_lead import BusinessLead
from app.models.business_package import BusinessPackage
```

and in `__all__`:

```python
    "BusinessLead",
    "BusinessPackage",
```

- [ ] **Step 3: Write the migration**

`micco-backend/backend/alembic/versions/012_add_business_leads.py`:

```python
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
```

- [ ] **Step 4: Apply the migration**

Run: `cd micco-backend/backend && alembic upgrade head`
Expected: no errors, `alembic current` shows `012_add_business_leads (head)`.

- [ ] **Step 5: Commit**

```bash
git add app/models/business_lead.py app/models/__init__.py alembic/versions/012_add_business_leads.py
git commit -m "feat: add BusinessLead model and migration"
```

---

## Task 2: `LeadSentinelFilter`

**Files:**
- Create: `micco-backend/backend/app/services/business_lead_sentinel.py`
- Test: `micco-backend/backend/tests/unit/test_business_lead_sentinel.py`

**Interfaces:**
- Produces: `LeadSentinelFilter` (class), `LeadDraft` (`NamedTuple` with `summary: str`, `package_ids: list[int]`), `SENTINEL_OPEN = "[[LEAD:"` — all in `app.services.business_lead_sentinel`. `filter.feed(text: str) -> str`, `filter.finish() -> tuple[str, LeadDraft | None]`.
- Consumes: nothing from other tasks — this module is self-contained, same as `RecommendationSentinelFilter`.

- [ ] **Step 1: Write the failing tests**

`micco-backend/backend/tests/unit/test_business_lead_sentinel.py`:

```python
"""Stripping the lead-handoff sentinel out of a streaming answer.

Sibling of tests/unit/test_business_recommendation.py. The property under
test is the same: the marker must never reach the screen, no matter where
chunk boundaries fall, and a malformed body must fail closed to "no lead".
"""
from __future__ import annotations

import pytest

from app.services.business_lead_sentinel import (
    SENTINEL_OPEN,
    LeadDraft,
    LeadSentinelFilter,
)


def run(chunks: list[str]) -> tuple[str, LeadDraft | None]:
    """Feed `chunks` through the filter; return (displayed text, draft)."""
    sentinel = LeadSentinelFilter()
    shown = "".join(sentinel.feed(chunk) for chunk in chunks)
    trailing, draft = sentinel.finish()
    return shown + trailing, draft


# ─── The marker never reaches the screen ───────────────────────────

def test_sentinel_is_stripped_from_a_single_chunk():
    shown, draft = run(["Vâng, tôi ghi nhận nhu cầu.[[LEAD: 3,7|Cần 200 tấn anfo, ngân sách 200 triệu]]"])

    assert shown == "Vâng, tôi ghi nhận nhu cầu."
    assert draft == LeadDraft(summary="Cần 200 tấn anfo, ngân sách 200 triệu", package_ids=[3, 7])


def test_sentinel_split_across_every_possible_boundary_never_leaks():
    answer = "Vâng, tôi ghi nhận nhu cầu."
    full = f"{answer}[[LEAD: 3|Cần tư vấn hợp đồng]]"

    for split in range(len(full) + 1):
        shown, draft = run([full[:split], full[split:]])
        assert shown == answer, f"leaked at split {split}: {shown!r}"
        assert draft == LeadDraft(summary="Cần tư vấn hợp đồng", package_ids=[3])


def test_sentinel_fed_one_character_at_a_time_never_leaks():
    shown, draft = run(list("Đã rõ.[[LEAD: 1|Muốn ký hợp đồng]]"))

    assert shown == "Đã rõ."
    assert draft == LeadDraft(summary="Muốn ký hợp đồng", package_ids=[1])


def test_partial_marker_is_held_back_until_it_is_disproved():
    sentinel = LeadSentinelFilter()

    assert sentinel.feed("Đã rõ.[[LE") == "Đã rõ."
    assert sentinel.feed("AD: 1|Cần báo giá]]") == ""
    trailing, draft = sentinel.finish()
    assert trailing == ""
    assert draft == LeadDraft(summary="Cần báo giá", package_ids=[1])


def test_text_that_looked_like_a_marker_is_released_at_finish():
    shown, draft = run(["Giá theo m[[3", ""])

    assert shown == "Giá theo m[[3"
    assert draft is None


def test_truncated_sentinel_is_dropped_not_shown():
    shown, draft = run(["Đã rõ.[[LEAD: 1|Cần báo giá"])

    assert shown == "Đã rõ."
    assert draft is None


# ─── Parsing ───────────────────────────────────────────────────────

def test_ids_before_the_pipe_are_parsed_loosely():
    _, draft = run(["Xong.[[LEAD: 3, 7 ,12|Cần tư vấn]]"])

    assert draft == LeadDraft(summary="Cần tư vấn", package_ids=[3, 7, 12])


def test_empty_ids_before_the_pipe_yields_no_packages():
    """The customer may want to buy without naming a specific package."""
    _, draft = run(["Xong.[[LEAD: |Cần tư vấn hợp đồng tổng thể]]"])

    assert draft == LeadDraft(summary="Cần tư vấn hợp đồng tổng thể", package_ids=[])


def test_missing_pipe_is_malformed_and_drops_the_lead():
    """Fail closed: a body with no '|' cannot be split into ids and summary."""
    shown, draft = run(["Xong.[[LEAD: chỉ có ids không có tóm tắt]]"])

    assert shown == "Xong."
    assert draft is None


def test_empty_summary_after_the_pipe_drops_the_lead():
    _, draft = run(["Xong.[[LEAD: 1|   ]]"])

    assert draft is None


def test_summary_may_itself_contain_a_pipe_character():
    """Only the first '|' is a delimiter; the rest belongs to the summary."""
    _, draft = run(["Xong.[[LEAD: 1|Cần A|B|C]]"])

    assert draft == LeadDraft(summary="Cần A|B|C", package_ids=[1])


def test_a_second_sentinel_is_ignored_the_first_wins():
    shown, draft = run(["A.[[LEAD: 1|Đầu tiên]]B.[[LEAD: 2|Thứ hai]]"])

    assert shown == "A.B."
    assert draft == LeadDraft(summary="Đầu tiên", package_ids=[1])


def test_runaway_marker_is_released_as_text_rather_than_buffered_forever():
    tail = "x" * 700
    shown, draft = run([f"Mở ngoặc [[LEAD: {tail}"])

    assert tail in shown
    assert draft is None


def test_answer_without_a_sentinel_passes_through_untouched():
    text = "Micco cung cấp thuốc nổ công nghiệp cho mỏ đá lộ thiên."

    shown, draft = run([text])

    assert shown == text
    assert draft is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd micco-backend/backend && pytest tests/unit/test_business_lead_sentinel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.business_lead_sentinel'`.

- [ ] **Step 3: Write the implementation**

`micco-backend/backend/app/services/business_lead_sentinel.py`:

```python
"""Stripping the lead-handoff sentinel out of a streaming answer.

Sibling of RecommendationSentinelFilter (app/services/business_recommendation
.py): same trailing-prefix buffering technique, but this sentinel carries two
payload parts — candidate package ids and a free-text need summary — joined
by "|". A malformed body (no "|", or an empty summary) must fail closed to
"no lead", exactly as a malformed suggestion body fails closed to "no
suggestions": a half-parsed lead must never reach sales.

Not built on RecommendationSentinelFilter for the same reason that class is
not built on ToolCallStreamParser: each sentinel needs its own fail-closed
rule, and sharing a base class would blur that.
"""
from __future__ import annotations

import logging
import re
from typing import NamedTuple

logger = logging.getLogger(__name__)

SENTINEL_OPEN = "[[LEAD:"
SENTINEL_CLOSE = "]]"

_ID_RE = re.compile(r"\d+")

# A summary is prose, not a short id list, so this sentinel tolerates a wider
# body than RecommendationSentinelFilter's 200 chars before giving up on it.
_MAX_SENTINEL_BODY = 600


class LeadDraft(NamedTuple):
    summary: str
    package_ids: list[int]


class LeadSentinelFilter:
    """Strips the lead-handoff sentinel out of a streaming answer.

    Feed each text delta to :meth:`feed` and stream what it returns. Call
    :meth:`finish` once the stream ends to get any held-back text plus the
    parsed draft — ``None`` when no well-formed sentinel was seen.
    """

    def __init__(self) -> None:
        self._pending = ""
        self._in_sentinel = False
        self._body: str | None = None

    def feed(self, text: str) -> str:
        """Consume a delta, return the part that is safe to display now."""
        if not text:
            return ""

        self._pending += text
        emitted: list[str] = []

        while True:
            if self._in_sentinel:
                if SENTINEL_CLOSE not in self._pending:
                    if len(self._pending) > _MAX_SENTINEL_BODY:
                        logger.warning(
                            "business chat: lead sentinel exceeded %d chars, "
                            "treating it as text",
                            _MAX_SENTINEL_BODY,
                        )
                        emitted.append(self._pending)
                        self._pending = ""
                        self._in_sentinel = False
                    break

                body, self._pending = self._pending.split(SENTINEL_CLOSE, 1)
                self._in_sentinel = False
                # First sentinel wins: a second one is unexpected model
                # output, and the first draft already captured the need.
                if self._body is None:
                    self._body = body
                continue

            if SENTINEL_OPEN in self._pending:
                before, rest = self._pending.split(SENTINEL_OPEN, 1)
                if before:
                    emitted.append(before)
                self._pending = rest
                self._in_sentinel = True
                continue

            safe = _safe_prefix_length(self._pending, SENTINEL_OPEN)
            if safe:
                emitted.append(self._pending[:safe])
                self._pending = self._pending[safe:]
            break

        return "".join(emitted)

    def finish(self) -> tuple[str, "LeadDraft | None"]:
        """End of stream: leftover displayable text and the parsed draft.

        Text held back as a possible sentinel start is released here, since it
        never became one. Text held back *inside* an unterminated sentinel is
        dropped — a truncated marker is not something a customer should read.
        """
        leftover = ""
        if self._in_sentinel:
            if self._pending:
                logger.info(
                    "business chat: dropping unterminated lead sentinel (%d chars held)",
                    len(self._pending),
                )
        else:
            leftover = self._pending

        self._pending = ""
        self._in_sentinel = False
        return leftover, _parse_draft(self._body)


def _parse_draft(body: str | None) -> "LeadDraft | None":
    """Ids-and-summary out of a sentinel body, or None if it is malformed."""
    if body is None:
        return None
    if "|" not in body:
        logger.info("business chat: lead sentinel missing '|', dropping")
        return None
    ids_part, summary_part = body.split("|", 1)
    summary = summary_part.strip()
    if not summary:
        logger.info("business chat: lead sentinel has an empty summary, dropping")
        return None
    package_ids = [int(match.group()) for match in _ID_RE.finditer(ids_part)]
    return LeadDraft(summary=summary, package_ids=package_ids)


def _safe_prefix_length(buf: str, marker: str) -> int:
    """Length of `buf` guaranteed not to be the start of `marker`."""
    max_suffix = min(len(marker) - 1, len(buf))
    for length in range(max_suffix, 0, -1):
        if buf[-length:] == marker[:length]:
            return len(buf) - length
    return len(buf)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd micco-backend/backend && pytest tests/unit/test_business_lead_sentinel.py -v`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add app/services/business_lead_sentinel.py tests/unit/test_business_lead_sentinel.py
git commit -m "feat: add LeadSentinelFilter for the [[LEAD:...]] chat sentinel"
```

---

## Task 3: Prompt contract for `[[LEAD:...]]`

**Files:**
- Modify: `micco-backend/backend/app/api/business_chat_prompt.py`
- Modify: `micco-backend/backend/tests/unit/test_business_chat_prompt.py`

**Interfaces:**
- Produces: `LEAD_CONTRACT` (module-level `str` constant) in `app.api.business_chat_prompt`, always included by `build_business_system_prompt(context, catalog_digest="")` — regardless of whether `catalog_digest` is empty, unlike `SUGGESTION_CONTRACT`.
- Consumes: nothing new — extends the existing `build_business_system_prompt`.

- [ ] **Step 1: Write the failing tests**

Add to `micco-backend/backend/tests/unit/test_business_chat_prompt.py` (append at the end of the file):

```python
from app.api.business_chat_prompt import LEAD_CONTRACT


def test_lead_contract_is_always_in_the_prompt_even_without_a_catalogue():
    """Unlike SUGGESTION_CONTRACT, the lead sentinel has nothing to do with
    the catalogue existing — a customer can want a contract with no specific
    package in mind."""
    prompt = build_business_system_prompt("noi dung tai lieu")

    assert LEAD_CONTRACT in prompt


def test_lead_contract_comes_before_the_guardrail():
    prompt = build_business_system_prompt("noi dung tai lieu", "danh muc")

    assert prompt.index(LEAD_CONTRACT) < prompt.index(BUSINESS_HARD_GUARDRAIL)


def test_lead_contract_mentions_the_sentinel_marker():
    assert "[[LEAD:" in LEAD_CONTRACT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd micco-backend/backend && pytest tests/unit/test_business_chat_prompt.py -v`
Expected: FAIL — `ImportError: cannot import name 'LEAD_CONTRACT'`.

- [ ] **Step 3: Write the implementation**

Modify `micco-backend/backend/app/api/business_chat_prompt.py`. Insert this new constant right after `SUGGESTION_CONTRACT` (after line 72, before `def build_business_system_prompt`):

```python
# Contract for the lead-handoff sentinel. Always included — unlike
# SUGGESTION_CONTRACT, this does not depend on the catalogue having rows: a
# customer can want a contract without naming a specific package.
#
# The sentinel travels down the same stream as the prose, so it is stripped
# before display by LeadSentinelFilter (app/services/business_lead_sentinel.py).
LEAD_CONTRACT = """Cách chuyển yêu cầu cho đội kinh doanh:

- Khi khách thể hiện ý định **mua/đặt hàng/ký hợp đồng** rõ ràng (không chỉ hỏi thông tin), trả lời như bình thường rồi kết thúc câu trả lời bằng đúng một dòng cuối theo mẫu:
  [[LEAD: id1,id2|tóm tắt ngắn gọn nhu cầu của khách, kèm ngân sách nếu khách có nêu]]
  Để trống trước dấu | nếu không có gói cụ thể nào liên quan.
- Không dùng dòng này cùng lúc với dòng gợi ý gói — chỉ chọn một trong hai, hoặc không dòng nào nếu khách chỉ đang hỏi thông tin. Gợi ý gói dùng khi nhu cầu còn rộng; dòng này dùng khi ý định mua/ký đã rõ.
- Dòng đó là tín hiệu cho hệ thống, không phải câu văn. Không giải thích nó, không nhắc tới nó, không viết gì sau nó."""
```

Then modify `build_business_system_prompt` (the existing function) to always append `LEAD_CONTRACT` before the guardrail:

```python
def build_business_system_prompt(context: str, catalog_digest: str = "") -> str:
    """Assemble the portal system prompt around the retrieved context.

    Order is: persona, retrieved context, catalogue and its contract, lead
    contract, guardrail. The guardrail goes last on purpose — see the module
    docstring — so neither document text nor a package name written by an
    Admin can be read as an instruction that overrides the rules.
    """
    parts = [
        BUSINESS_SYSTEM_PROMPT,
        f"{CONTEXT_HEADING}\n{context}",
    ]
    if catalog_digest:
        parts.append(f"{CATALOG_HEADING}\n{catalog_digest}\n\n{SUGGESTION_CONTRACT}")
    parts.append(LEAD_CONTRACT)
    parts.append(BUSINESS_HARD_GUARDRAIL)
    return "\n\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd micco-backend/backend && pytest tests/unit/test_business_chat_prompt.py -v`
Expected: PASS (all cases, including the pre-existing ones — `test_guardrail_ends_the_prompt` still holds since the guardrail is still appended last).

- [ ] **Step 5: Commit**

```bash
git add app/api/business_chat_prompt.py tests/unit/test_business_chat_prompt.py
git commit -m "feat: add LEAD_CONTRACT to the business chat system prompt"
```

---

## Task 4: Wire the sentinel into `stream_business_chat` — SSE `lead_prompt`

**Files:**
- Modify: `micco-backend/backend/app/services/business_chat.py`
- Modify: `micco-backend/backend/app/api/business_chat.py` (docstring only)
- Create: `micco-backend/backend/tests/integration/test_business_lead_prompt_stream.py`

**Interfaces:**
- Consumes: `LeadSentinelFilter`, `LeadDraft` from `app.services.business_lead_sentinel` (Task 2); `resolve_recommendations`, `to_card` from `app.services.business_packages` (already imported in `business_chat.py`).
- Produces: new SSE event `("lead_prompt", {"summary": str, "packages": [BusinessPackageCard-shaped dict, ...]})`, yielded from `stream_business_chat` before `complete`. Not persisted, not added to the `complete` payload.

- [ ] **Step 1: Write the failing tests**

`micco-backend/backend/tests/integration/test_business_lead_prompt_stream.py`:

```python
"""Lead-handoff proposal through the portal chat stream.

The chat stream only ever *proposes* a lead — see
app.services.business_lead_sentinel — and never writes one. These tests hold
that promise: the sentinel never reaches the customer, a card only ever
describes a package that is really in the active catalogue, and a malformed
sentinel degrades to a clean answer with no lead_prompt event.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services import business_chat
from app.services.business_rag import (
    BUSINESS_AUDIENCE,
    BusinessRetrievalResult,
    BusinessSource,
)
from app.services.llm.types import StreamChunk

STREAM_URL = "/api/v1/business/chat/stream"

_CONTEXT = "[1] Bang gia san pham | tr.3\nAnfo dùng cho mỏ đá lộ thiên."


@pytest.fixture
def stub_retrieval(monkeypatch):
    async def _fake_search(db, question, top_k=5):
        return BusinessRetrievalResult(
            context=_CONTEXT,
            sources=(BusinessSource(label="Bang gia san pham", page_no=3),),
            allowed_document_ids=(11,),
        )

    monkeypatch.setattr(business_chat, "business_search", _fake_search)


@pytest.fixture
async def business_workspace(make_workspace):
    return await make_workspace(
        name="Cong khai doanh nghiep", audience=BUSINESS_AUDIENCE
    )


@pytest.fixture
async def catalog(make_package):
    return [
        await make_package(name="Cung ứng thuốc nổ", category="Vật liệu nổ", sort_order=10),
        await make_package(name="Dịch vụ nổ mìn trọn gói", category="Dịch vụ", sort_order=20),
    ]


def parse_sse(body: str) -> list[tuple[str, dict]]:
    import json

    events: list[tuple[str, dict]] = []
    for frame in body.split("\n\n"):
        name = payload = None
        for line in frame.splitlines():
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                payload = json.loads(line[len("data:"):].strip())
        if name is not None and payload is not None:
            events.append((name, payload))
    return events


def names(events) -> list[str]:
    return [name for name, _ in events]


def payload_of(events, name: str) -> dict:
    for event_name, payload in events:
        if event_name == name:
            return payload
    raise AssertionError(f"no {name!r} event in {names(events)}")


def streamed_text(events) -> str:
    return "".join(p["text"] for n, p in events if n == "delta")


async def ask(client: AsyncClient, message: str = "Tôi muốn ký hợp đồng cung cấp anfo"):
    response = await client.post(STREAM_URL, json={"message": message})
    assert response.status_code == 200, response.text
    return parse_sse(response.text), response.text


async def test_lead_intent_returns_prose_and_a_lead_prompt(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    mock_llm_provider.chunks = [
        StreamChunk(type="text", text="Vâng, tôi ghi nhận nhu cầu của bạn. "),
        StreamChunk(
            type="text",
            text=f"[[LEAD: {catalog[0].id}|Cần 200 tấn anfo cho mỏ đá, ngân sách khoảng 200 triệu]]",
        ),
    ]

    events, raw = await ask(business_client)

    assert "LEAD" not in raw
    assert streamed_text(events).strip() == "Vâng, tôi ghi nhận nhu cầu của bạn."
    prompt = payload_of(events, "lead_prompt")
    assert prompt["summary"] == "Cần 200 tấn anfo cho mỏ đá, ngân sách khoảng 200 triệu"
    assert [p["name"] for p in prompt["packages"]] == ["Cung ứng thuốc nổ"]


async def test_lead_prompt_arrives_before_complete(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    mock_llm_provider.chunks = [
        StreamChunk(type="text", text=f"Đã rõ.[[LEAD: |Cần tư vấn hợp đồng tổng thể]]"),
    ]

    events, _ = await ask(business_client)

    order = names(events)
    assert order.index("lead_prompt") < order.index("complete")
    assert order[-1] == "complete"


async def test_lead_prompt_with_no_package_still_carries_a_summary(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    mock_llm_provider.chunks = [
        StreamChunk(type="text", text="Đã rõ.[[LEAD: |Cần tư vấn hợp đồng tổng thể]]"),
    ]

    events, _ = await ask(business_client)

    prompt = payload_of(events, "lead_prompt")
    assert prompt["summary"] == "Cần tư vấn hợp đồng tổng thể"
    assert prompt["packages"] == []


async def test_hallucinated_package_id_is_dropped_from_the_lead_prompt(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    mock_llm_provider.chunks = [
        StreamChunk(type="text", text="Đã rõ.[[LEAD: 9999|Cần tư vấn]]"),
    ]

    events, raw = await ask(business_client)

    prompt = payload_of(events, "lead_prompt")
    assert prompt["packages"] == []


async def test_truncated_lead_sentinel_leaves_a_clean_answer_and_no_prompt(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    mock_llm_provider.chunks = [StreamChunk(type="text", text="Đã rõ.[[LEAD: 1|Cần báo giá")]

    events, raw = await ask(business_client)

    assert "LEAD" not in raw
    assert streamed_text(events) == "Đã rõ."
    assert "lead_prompt" not in names(events)


async def test_no_sentinel_means_no_lead_prompt_event(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    mock_llm_provider.chunks = [StreamChunk(type="text", text="Anfo dùng cho mỏ đá lộ thiên.")]

    events, _ = await ask(business_client)

    assert "lead_prompt" not in names(events)


async def test_lead_prompt_is_not_carried_in_the_complete_payload(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    """The draft is ephemeral — the stand-alone event is the only channel."""
    mock_llm_provider.chunks = [
        StreamChunk(type="text", text="Đã rõ.[[LEAD: |Cần tư vấn hợp đồng tổng thể]]")
    ]

    events, _ = await ask(business_client)

    assert "lead_prompt" not in payload_of(events, "complete")


async def test_lead_prompt_is_not_persisted_to_history(
    business_client: AsyncClient, business_workspace, catalog, stub_retrieval, mock_llm_provider
):
    mock_llm_provider.chunks = [
        StreamChunk(type="text", text="Đã rõ.[[LEAD: |Cần tư vấn hợp đồng tổng thể]]")
    ]
    await ask(business_client)

    history = await business_client.get("/api/v1/business/chat/history")
    messages = history.json()["data"]["messages"]

    assert "leadPrompt" not in messages[-1]
    assert "lead_prompt" not in history.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd micco-backend/backend && pytest tests/integration/test_business_lead_prompt_stream.py -v`
Expected: FAIL — no `lead_prompt` event is ever emitted yet (assertion errors, not import errors).

- [ ] **Step 3: Write the implementation**

Modify `micco-backend/backend/app/services/business_chat.py`.

Add to the imports (near the existing `from app.services.business_recommendation import RecommendationSentinelFilter`):

```python
from app.services.business_lead_sentinel import LeadSentinelFilter
```

Replace the streaming block (currently lines 225-277) with:

```python
    provider = get_llm_provider()
    recommendation_sentinel = RecommendationSentinelFilter()
    lead_sentinel = LeadSentinelFilter()
    parts: list[str] = []
    failed = False

    try:
        async for text in _stream_answer(provider, system_prompt, history, question):
            # Two independent filters, chained: each is responsible only for
            # not letting its own marker reach the screen. Chaining them is
            # safe even if the markers share a "[[" prefix, because the
            # second filter re-buffers whatever the first one lets through —
            # see the design spec for why this composes correctly.
            after_recommendation = recommendation_sentinel.feed(text)
            visible = lead_sentinel.feed(after_recommendation)
            if visible:
                parts.append(visible)
                yield ("delta", {"text": visible})
    except Exception:
        logger.exception("business chat: LLM streaming failed")
        failed = True

    reco_trailing, suggested_ids = recommendation_sentinel.finish()
    # Text released by the first filter at finish() has never been through
    # the second filter yet — it still needs to be checked and buffered.
    visible_trailing = lead_sentinel.feed(reco_trailing)
    lead_trailing, lead_draft = lead_sentinel.finish()
    trailing = visible_trailing + lead_trailing
    if trailing:
        parts.append(trailing)
        yield ("delta", {"text": trailing})

    answer = "".join(parts).strip()
    _log_llm_call(provider, system_prompt, question, answer, started)

    if failed or not answer:
        # Whatever streamed is already on screen, so keep it — but say the turn
        # did not finish rather than presenting a truncated answer as complete.
        if answer:
            await _persist(db, workspace.id, user.id, "assistant", answer, sources)
        yield ("error", {"message": _ERROR_MESSAGE})
        return

    # Suggestions are an addition, never a precondition: an id the model made
    # up is dropped here rather than looked up, and the answer stands either
    # way.
    cards = [to_card(p) for p in resolve_recommendations(suggested_ids, packages)]
    if cards:
        yield ("recommendations", {"packages": cards})

    # A lead proposal is ephemeral: shown once during this live stream only,
    # never persisted and never repeated in the complete/history payloads. If
    # the customer reloads before confirming, the draft is gone — they simply
    # ask again.
    if lead_draft is not None:
        lead_cards = [to_card(p) for p in resolve_recommendations(lead_draft.package_ids, packages)]
        yield ("lead_prompt", {"summary": lead_draft.summary, "packages": lead_cards})

    message_id = await _persist(
        db, workspace.id, user.id, "assistant", answer, sources, cards
    )
    yield (
        "complete",
        {
            "message_id": message_id,
            "answer": answer,
            "sources": sources,
            "recommendations": cards,
        },
    )
```

Modify `micco-backend/backend/app/api/business_chat.py` — update the module docstring's SSE event list (around line 11-16) to add `lead_prompt`:

```python
SSE events emitted by POST /stream:
  - status:   {"step": str, "detail": str}
  - sources:  {"sources": [{"label": str, "page_no": int}]}
  - delta:    {"text": str}
  - recommendations: {"packages": [BusinessPackageCard, ...]}
  - lead_prompt: {"summary": str, "packages": [BusinessPackageCard, ...]}
  - complete: {"message_id": str, "answer": str, "sources": [...]}
  - error:    {"message": str}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd micco-backend/backend && pytest tests/integration/test_business_lead_prompt_stream.py tests/integration/test_business_recommendations_api.py tests/unit/test_business_lead_sentinel.py -v`
Expected: PASS. Running the existing `test_business_recommendations_api.py` alongside confirms the recommendation sentinel still behaves exactly as before after being chained with the new filter.

- [ ] **Step 5: Commit**

```bash
git add app/services/business_chat.py app/api/business_chat.py tests/integration/test_business_lead_prompt_stream.py
git commit -m "feat: emit lead_prompt SSE event when the chat detects purchase intent"
```

---

## Task 5: `notify_lead_created` — n8n outbound webhook

**Files:**
- Modify: `micco-backend/backend/app/services/n8n_webhook.py`
- Modify: `micco-backend/backend/tests/unit/test_n8n_webhook.py`

**Interfaces:**
- Consumes: `app.models.business_lead.BusinessLead` (Task 1), `app.models.business_package.BusinessPackage` (existing).
- Produces: `async def notify_lead_created(lead_id: int) -> None` in `app.services.n8n_webhook`. Called with a `BusinessLead.id` by Task 6's endpoint via `BackgroundTasks.add_task`.

- [ ] **Step 1: Write the failing tests**

Append to `micco-backend/backend/tests/unit/test_n8n_webhook.py`:

```python
from app.models.business_lead import BusinessLead
from app.models.business_package import BusinessPackage


class _FakePackageScalars:
    def __init__(self, packages):
        self._packages = packages

    def all(self):
        return self._packages


class _FakePackageResult:
    def __init__(self, packages):
        self._packages = packages

    def scalars(self):
        return _FakePackageScalars(self._packages)


class _FakeLeadDb:
    """Dispatches select(BusinessLead)/select(BusinessPackage) to fixtures."""

    def __init__(self, lead=None, packages=None):
        self._lead = lead
        self._packages = packages or []

    async def execute(self, stmt):
        target = stmt.column_descriptions[0]["type"]
        if target is BusinessLead:
            return _FakeResult(self._lead)
        if target is BusinessPackage:
            return _FakePackageResult(self._packages)
        return _FakeResult(None)


def _patch_lead_db(monkeypatch, lead=None, packages=None):
    fake_db = _FakeLeadDb(lead=lead, packages=packages)
    monkeypatch.setattr(
        "app.core.database.async_session_maker", lambda: _FakeSessionCM(fake_db)
    )
    return fake_db


def _fake_lead(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=5,
        company_name="Cong ty TNHH Test",
        contact_phone="0900000000",
        contact_email="business@example.test",
        summary="Cần 200 tấn anfo, ngân sách khoảng 200 triệu",
        package_ids=[1],
        created_at=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_package(**overrides) -> SimpleNamespace:
    defaults = dict(id=1, name="Cung ứng thuốc nổ")
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


async def test_notify_lead_created_noop_when_url_not_configured(monkeypatch):
    monkeypatch.setattr(n8n_webhook.settings, "N8N_WEBHOOK_URL", "")

    await n8n_webhook.notify_lead_created(5)

    assert _FakeAsyncClient.last_instance is None


async def test_notify_lead_created_skips_when_lead_missing(monkeypatch):
    monkeypatch.setattr(n8n_webhook.settings, "N8N_WEBHOOK_URL", "https://example.test/webhook")
    _patch_lead_db(monkeypatch, lead=None)

    await n8n_webhook.notify_lead_created(999)

    assert _FakeAsyncClient.last_instance is None


async def test_notify_lead_created_posts_expected_payload(monkeypatch):
    monkeypatch.setattr(n8n_webhook.settings, "N8N_WEBHOOK_URL", "https://example.test/webhook")
    lead = _fake_lead()
    package = _fake_package()
    _patch_lead_db(monkeypatch, lead=lead, packages=[package])

    await n8n_webhook.notify_lead_created(lead.id)

    client = _FakeAsyncClient.last_instance
    assert client is not None
    url, payload = client.posted[0]
    assert url == "https://example.test/webhook"
    assert payload["event"] == "lead.created"
    assert payload["lead"]["id"] == lead.id
    assert payload["lead"]["company_name"] == "Cong ty TNHH Test"
    assert payload["lead"]["contact_email"] == "business@example.test"
    assert payload["lead"]["summary"] == lead.summary
    assert payload["lead"]["packages"] == [{"id": 1, "name": "Cung ứng thuốc nổ"}]


async def test_notify_lead_created_with_no_packages(monkeypatch):
    monkeypatch.setattr(n8n_webhook.settings, "N8N_WEBHOOK_URL", "https://example.test/webhook")
    lead = _fake_lead(package_ids=[])
    _patch_lead_db(monkeypatch, lead=lead, packages=[])

    await n8n_webhook.notify_lead_created(lead.id)

    _, payload = _FakeAsyncClient.last_instance.posted[0]
    assert payload["lead"]["packages"] == []


async def test_notify_lead_created_swallows_http_errors(monkeypatch):
    monkeypatch.setattr(n8n_webhook.settings, "N8N_WEBHOOK_URL", "https://example.test/webhook")
    lead = _fake_lead()
    _patch_lead_db(monkeypatch, lead=lead, packages=[])

    class _FailingClient(_FakeAsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.response = _FakeResponse(status_code=500)

    monkeypatch.setattr(n8n_webhook.httpx, "AsyncClient", _FailingClient)

    # Must not raise even though the webhook responds with an error.
    await n8n_webhook.notify_lead_created(lead.id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd micco-backend/backend && pytest tests/unit/test_n8n_webhook.py -v -k lead_created`
Expected: FAIL — `AttributeError: module 'app.services.n8n_webhook' has no attribute 'notify_lead_created'`.

- [ ] **Step 3: Write the implementation**

Append to `micco-backend/backend/app/services/n8n_webhook.py`:

```python
async def notify_lead_created(lead_id: int) -> None:
    """Post a lead.created event to the configured n8n webhook.

    Same event type as notify_document_uploaded (this is the same n8n
    instance, discriminated by the "event" field) — no new secret or URL.
    """
    if not settings.N8N_WEBHOOK_URL:
        logger.info(
            f"n8n webhook: N8N_WEBHOOK_URL not configured, skipping notify for lead {lead_id}"
        )
        return

    try:
        from sqlalchemy import select

        from app.core.database import async_session_maker
        from app.models.business_lead import BusinessLead
        from app.models.business_package import BusinessPackage

        async with async_session_maker() as db:
            result = await db.execute(select(BusinessLead).where(BusinessLead.id == lead_id))
            lead = result.scalar_one_or_none()
            if lead is None:
                logger.warning(f"n8n webhook: lead {lead_id} not found, skipping notify")
                return

            packages: list[dict] = []
            if lead.package_ids:
                pkg_result = await db.execute(
                    select(BusinessPackage).where(BusinessPackage.id.in_(lead.package_ids))
                )
                packages = [{"id": p.id, "name": p.name} for p in pkg_result.scalars().all()]

            payload = {
                "event": "lead.created",
                "lead": {
                    "id": lead.id,
                    "company_name": lead.company_name,
                    "contact_phone": lead.contact_phone,
                    "contact_email": lead.contact_email,
                    "summary": lead.summary,
                    "packages": packages,
                    "created_at": lead.created_at.isoformat() if lead.created_at else None,
                },
            }

        logger.info(f"n8n webhook: notifying lead.created for lead {lead_id} -> {settings.N8N_WEBHOOK_URL}")

        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(settings.N8N_WEBHOOK_URL, json=payload)
            response.raise_for_status()

        logger.info(f"n8n webhook: lead {lead_id} notified successfully (status {response.status_code})")
    except Exception as e:
        logger.warning(f"n8n webhook call failed for lead {lead_id}: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd micco-backend/backend && pytest tests/unit/test_n8n_webhook.py -v`
Expected: PASS — every existing `notify_document_uploaded` test plus the new `notify_lead_created` tests.

- [ ] **Step 5: Commit**

```bash
git add app/services/n8n_webhook.py tests/unit/test_n8n_webhook.py
git commit -m "feat: add notify_lead_created n8n webhook"
```

---

## Task 6: `POST /api/v1/business/leads`

**Files:**
- Modify: `micco-backend/backend/app/schemas/business.py`
- Create: `micco-backend/backend/app/api/business_leads.py`
- Modify: `micco-backend/backend/app/api/router.py`
- Create: `micco-backend/backend/tests/integration/test_business_leads_api.py`

**Interfaces:**
- Consumes: `BusinessLead` (Task 1), `notify_lead_created` (Task 5), `resolve_recommendations`/`get_active_packages` (existing, `app.services.business_packages`), `get_current_business_user` (existing, `app.core.business_deps`).
- Produces: `POST /api/v1/business/leads` — request `{"summary": str, "package_ids": [int, ...]}`, response `{"data": {"id": int, "created_at": str}, "meta": {}}`.

- [ ] **Step 1: Write the failing tests**

`micco-backend/backend/tests/integration/test_business_leads_api.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd micco-backend/backend && pytest tests/integration/test_business_leads_api.py -v`
Expected: FAIL — `404 Not Found` (route does not exist yet) / `ModuleNotFoundError` for `app.api.business_leads`.

- [ ] **Step 3: Write the implementation**

Modify `micco-backend/backend/app/schemas/business.py` — append at the end of the file, after `BusinessChatCleared`:

```python
# ─── Lead handoff (Phase 5) ─────────────────────────────────────────
# The customer's confirmation of a chat-proposed [[LEAD:...]] draft (see
# app.services.business_lead_sentinel). extra="forbid" for the same reason as
# BusinessChatRequest: nothing about who is sending this or when is meant to
# come from the client.


class BusinessLeadCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(..., min_length=1, max_length=1000)
    package_ids: list[int] = Field(default_factory=list)


class BusinessLeadCreated(BaseModel):
    id: int
    created_at: datetime
```

Create `micco-backend/backend/app/api/business_leads.py`:

```python
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
```

Modify `micco-backend/backend/app/api/router.py` — add the import next to the existing business imports (around line 12-13) and register the router next to the existing `business_chat_router` (around line 23-24):

```python
from app.api.business_leads import router as business_leads_router
```

```python
api_router.include_router(business_leads_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd micco-backend/backend && pytest tests/integration/test_business_leads_api.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend test suite**

Run: `cd micco-backend/backend && pytest tests/ -x --tb=short`
Expected: PASS (all tests, including every business/n8n test touched by this plan).

- [ ] **Step 6: Commit**

```bash
git add app/schemas/business.py app/api/business_leads.py app/api/router.py tests/integration/test_business_leads_api.py
git commit -m "feat: add POST /api/v1/business/leads endpoint"
```

---

## Task 7: Frontend — `businessApi.js` lead support

**Files:**
- Modify: `micco-frontend/src/business/businessApi.js`

**Interfaces:**
- Produces: `businessChatApi.createLead(summary, packageIds) -> Promise<{id, created_at}>`; `streamBusinessChat` handlers gain `onLeadPrompt(payload)` where `payload = {summary: string, packages: BusinessPackageCard[]}`.
- Consumes: `businessUrl`, `authHeaders`, `getBusinessToken`, `request` (all already in this file).

No backend test runner covers the frontend (per `CLAUDE.md`, verified with `/e2e-test` at the end of this plan) — this task is implemented directly, then exercised end-to-end once the UI pieces exist (Tasks 8-9).

- [ ] **Step 1: Add `createLead` to `businessChatApi`**

Modify `micco-frontend/src/business/businessApi.js` — extend the existing `businessChatApi` object (around line 101-107):

```javascript
export const businessChatApi = {
    /** GET /chat/history → {messages, total} */
    history: () => request('/chat/history'),

    /** DELETE /chat/history → {deleted} */
    clearHistory: () => request('/chat/history', { method: 'DELETE' }),

    /** POST /leads → {id, created_at} — confirm a chat-proposed lead draft */
    createLead: (summary, packageIds) =>
        request('/leads', { method: 'POST', body: { summary, package_ids: packageIds } }),
};
```

- [ ] **Step 2: Handle the `lead_prompt` SSE event**

Modify `micco-frontend/src/business/businessApi.js` — update `streamBusinessChat`'s handler signature and switch (around line 120-186):

```javascript
export async function streamBusinessChat(message, handlers = {}) {
    const {
        onStatus, onSources, onDelta, onRecommendations, onLeadPrompt, onComplete, onError,
    } = handlers;
```

Replace the `default` case in the `switch (chunk.event)` block:

```javascript
                    case 'lead_prompt':
                        onLeadPrompt?.({ summary: chunk.summary || '', packages: chunk.packages || [] });
                        break;
                    default:
                        // Unknown events are ignored, never shown.
                        break;
```

- [ ] **Step 3: Commit**

```bash
git add micco-frontend/src/business/businessApi.js
git commit -m "feat: add lead_prompt event and createLead to businessApi"
```

---

## Task 8: Frontend — `BusinessLeadPrompt` component

**Files:**
- Create: `micco-frontend/src/business/BusinessLeadPrompt.jsx`

**Interfaces:**
- Consumes: `businessChatApi.createLead` (Task 7).
- Produces: `<BusinessLeadPrompt summary={string} packages={BusinessPackageCard[]} />` — a React component with no required props beyond these two; manages its own "sent" state internally.

- [ ] **Step 1: Write the component**

`micco-frontend/src/business/BusinessLeadPrompt.jsx`:

```javascript
/**
 * Confirmation card for a chat-proposed lead (Phase 5).
 *
 * Not auto-submitted: the model only proposes — see BUSINESS_SYSTEM_PROMPT's
 * [[LEAD:...]] contract — and this component is the one place the customer
 * turns that proposal into a real request, via businessChatApi.createLead.
 * The draft itself is never persisted server-side, so this component's local
 * "sent" state is the only record of the click until the page is reloaded.
 */
import { useState } from 'react';
import { AlertCircle, Loader2, Send } from 'lucide-react';

import { businessChatApi } from './businessApi';

export default function BusinessLeadPrompt({ summary, packages }) {
    const [status, setStatus] = useState('idle'); // idle | sending | sent | dismissed | error

    if (!summary || status === 'dismissed') return null;

    const handleConfirm = async () => {
        setStatus('sending');
        try {
            await businessChatApi.createLead(summary, (packages || []).map((p) => p.id));
            setStatus('sent');
        } catch {
            setStatus('error');
        }
    };

    if (status === 'sent') {
        return (
            <section className="mt-6 pt-5 border-t border-[var(--p-line)]">
                <p className="text-[0.8125rem] text-[var(--p-ink-soft)]">
                    Đã gửi yêu cầu tới đội Micco. Chúng tôi sẽ liên hệ bạn sớm nhất.
                </p>
            </section>
        );
    }

    return (
        <section className="mt-6 pt-5 border-t border-[var(--p-line)]">
            <p className="p-eyebrow mb-2">Chuyển yêu cầu cho đội kinh doanh</p>
            <p className="text-[0.8125rem] leading-relaxed text-[var(--p-ink-soft)] mb-2">
                {summary}
            </p>
            {packages && packages.length > 0 && (
                <ul className="mb-3 space-y-1">
                    {packages.map((pkg) => (
                        <li key={pkg.id} className="text-[0.8125rem] text-[var(--p-ink-soft)]">
                            · {pkg.name}
                        </li>
                    ))}
                </ul>
            )}

            <div className="flex items-center gap-2">
                <button
                    type="button"
                    onClick={handleConfirm}
                    disabled={status === 'sending'}
                    className="p-btn !px-3 !py-2 !text-[0.8125rem]"
                >
                    {status === 'sending'
                        ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
                        : <Send className="w-3.5 h-3.5" aria-hidden="true" />}
                    Gửi yêu cầu tới đội Micco
                </button>
                <button
                    type="button"
                    onClick={() => setStatus('dismissed')}
                    disabled={status === 'sending'}
                    className="p-btn-ghost !px-3 !py-2 !text-[0.8125rem]"
                >
                    Bỏ qua
                </button>
            </div>

            {status === 'error' && (
                <p role="alert" className="mt-2 flex items-center gap-1.5 text-xs text-[var(--p-danger)]">
                    <AlertCircle className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                    Không gửi được, vui lòng thử lại.
                </p>
            )}
        </section>
    );
}
```

- [ ] **Step 2: Commit**

```bash
git add micco-frontend/src/business/BusinessLeadPrompt.jsx
git commit -m "feat: add BusinessLeadPrompt confirmation component"
```

---

## Task 9: Frontend — wire `lead_prompt` into the chat page

**Files:**
- Modify: `micco-frontend/src/business/BusinessChatPage.jsx`
- Modify: `micco-frontend/src/business/BusinessMessage.jsx`

**Interfaces:**
- Consumes: `onLeadPrompt` handler shape from Task 7, `BusinessLeadPrompt` from Task 8.

- [ ] **Step 1: Attach the lead prompt to the streaming message**

Modify `micco-frontend/src/business/BusinessChatPage.jsx`. In the initial history load (around line 47-55), add `leadPrompt: null` to each restored message (a reload never has a pending draft — see Task 4):

```javascript
                setMessages(
                    (data?.messages || []).map((m) => ({
                        id: m.message_id || nextId(),
                        role: m.role,
                        content: m.content,
                        sources: m.sources || [],
                        recommendations: m.recommendations || [],
                        leadPrompt: null,
                    })),
                );
```

In the `send` callback's initial message list (around line 92-103), add `leadPrompt: null` to the new assistant placeholder:

```javascript
        setMessages((current) => [
            ...current,
            { id: nextId(), role: 'user', content: question, sources: [], recommendations: [] },
            {
                id: nextId(),
                role: 'assistant',
                content: '',
                sources: [],
                recommendations: [],
                leadPrompt: null,
                status: 'Đang gửi câu hỏi',
            },
        ]);
```

Add the `onLeadPrompt` handler to the `streamBusinessChat` call (around line 105-120):

```javascript
        await streamBusinessChat(question, {
            onStatus: (detail) => updateLast(() => ({ status: detail })),
            onSources: (sources) => updateLast(() => ({ sources })),
            onDelta: (chunk) => updateLast((last) => ({
                content: last.content + chunk,
                status: '',
            })),
            onRecommendations: (packages) => updateLast(() => ({ recommendations: packages })),
            onLeadPrompt: (payload) => updateLast(() => ({ leadPrompt: payload })),
            onComplete: (payload) => updateLast(() => ({
                content: payload.answer,
                sources: payload.sources || [],
                recommendations: payload.recommendations || [],
                status: '',
            })),
            onError: (error) => updateLast(() => ({ status: '', error: error.message })),
        });
```

- [ ] **Step 2: Render `BusinessLeadPrompt` in the message**

Modify `micco-frontend/src/business/BusinessMessage.jsx`. Add the import:

```javascript
import BusinessLeadPrompt from './BusinessLeadPrompt';
```

Add the render call right after the existing `BusinessPackageCards` line (around line 84):

```javascript
            {!isStreaming && <BusinessPackageCards packages={message.recommendations} />}

            {!isStreaming && message.leadPrompt && (
                <BusinessLeadPrompt
                    summary={message.leadPrompt.summary}
                    packages={message.leadPrompt.packages}
                />
            )}
```

- [ ] **Step 3: Manual browser verification**

Per `CLAUDE.md`, run `/e2e-test` (or, at minimum, start both servers and drive the flow by hand in a real browser):

1. `cd micco-backend/backend && uvicorn app.main:app --reload --port 8000`
2. `cd micco-frontend && npm run dev`
3. Log in as a business account, ask a question that should trigger `[[LEAD:...]]` (e.g. "Tôi muốn ký hợp đồng cung cấp anfo cho mỏ đá của chúng tôi, ngân sách khoảng 200 triệu").
4. Confirm: the sentinel text never appears on screen; a confirmation card renders under the answer; clicking "Gửi yêu cầu tới đội Micco" shows the "Đã gửi" state and does not error; reloading the page does not resurrect the card (expected — it was never persisted).
5. Check the backend log for the `n8n webhook: notifying lead.created ...` (or `N8N_WEBHOOK_URL not configured, skipping` if unset locally) line to confirm the background task ran.

- [ ] **Step 4: Run the frontend lint**

Run: `cd micco-frontend && npm run lint`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add micco-frontend/src/business/BusinessChatPage.jsx micco-frontend/src/business/BusinessMessage.jsx
git commit -m "feat: wire lead_prompt confirmation card into the portal chat page"
```
