# n8n Agent Email Reply — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two n8n-facing tool endpoints so an n8n AI Agent can read a pending document's raw text and render its generated answer as a PDF, enabling natural-language email replies ("summarize this", "focus on section X") independent of the existing approve/reject flow.

**Architecture:** Two new endpoints on a new router (`app/api/n8n_agent.py`), authenticated the same way as the existing `approval-callback` endpoint (shared secret in `X-Webhook-Secret`, now factored into one dependency both use). A lightweight, non-LLM text extractor serves raw document text; a separate pure-Python PDF renderer turns the AI Agent's markdown answer into a PDF. Neither endpoint touches `approval_status`.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, PyMuPDF (`fitz`) for PDF text extraction, `fpdf2` for PDF generation, pytest + httpx `AsyncClient` for tests.

**Spec:** `docs/superpowers/specs/2026-09-12-n8n-agent-email-reply-design.md`

## Global Constraints

- No new secret: reuse `settings.N8N_CALLBACK_SECRET`, compared with `hmac.compare_digest`, fail-closed if unconfigured (spec §3, §Config).
- New endpoint responses are flat JSON, not wrapped in `{"data","meta"}` — matches the existing `approval-callback` precedent, not the general API envelope rule (spec §3).
- Zero LLM calls anywhere in this feature's backend code — all "understanding" happens in n8n's own AI Agent node (spec §Kiến trúc).
- `agent-content` only serves documents with `status == PENDING`; `agent-report` has no status restriction (spec §3, §4).
- Text extraction is capped at `AGENT_CONTENT_MAX_CHARS = 20_000` chars, with a `truncated` flag (spec §2).
- Every endpoint is `async def` (CLAUDE.md); request bodies get a typed Pydantic v2 schema (CLAUDE.md).
- Tests: mock all external/blocking calls per `.claude/rules/testing.md`, AAA structure, behavior-describing test names, use the `test_db`/`client`/`make_document`/`make_workspace` fixtures already in `tests/conftest.py`.
- Run tests from `micco-backend/backend/`: `pytest tests/ -x --tb=short` (or a narrower path per task).

---

### Task 1: Shared n8n webhook-secret dependency

**Files:**
- Modify: `micco-backend/backend/app/core/deps.py`
- Modify: `micco-backend/backend/app/api/documents.py:1-30` (imports), `:316-335` (`approval_callback` signature + auth check)
- Test: `micco-backend/backend/tests/integration/test_approval_callback.py` (existing — must keep passing unchanged)

**Interfaces:**
- Produces: `app.core.deps.verify_n8n_webhook_secret(document_id: int, x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret")) -> None` — raises `HTTPException(401, detail="Invalid webhook secret")` on missing/wrong/unconfigured secret. Consumed by every n8n-facing endpoint via `dependencies=[Depends(verify_n8n_webhook_secret)]`.

This is a pure refactor (no behavior change), so the "test" cycle is: confirm the existing suite is green before and after, instead of writing a new failing test.

- [ ] **Step 1: Run the existing approval-callback tests as a baseline**

Run: `cd micco-backend/backend && pytest tests/integration/test_approval_callback.py -v`
Expected: all tests PASS (this is the pre-refactor baseline).

- [ ] **Step 2: Add the shared dependency to `app/core/deps.py`**

Replace the full file content with:

```python
import hmac
import logging

from fastapi import Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def verify_n8n_webhook_secret(
    document_id: int,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
) -> None:
    """Shared auth for every endpoint n8n calls back into.

    Constant-time compare against N8N_CALLBACK_SECRET, fail-closed if the
    secret isn't configured. Used by approval-callback, agent-content, and
    agent-report so all three share one trust boundary and one place to
    change it.
    """
    if not settings.N8N_CALLBACK_SECRET or not x_webhook_secret or not hmac.compare_digest(
        x_webhook_secret, settings.N8N_CALLBACK_SECRET
    ):
        logger.warning(f"Rejected n8n webhook call for document {document_id}: invalid webhook secret")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")
```

- [ ] **Step 3: Refactor `approval_callback` in `app/api/documents.py` to use the dependency**

In the import block near the top, remove `hmac` (it becomes unused) and remove `Header` from the fastapi import:

```python
# before
import hmac
import os
...
from fastapi import APIRouter, Depends, Header, HTTPException, status, UploadFile, File, BackgroundTasks
```
```python
# after
import os
...
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
```

Add this import alongside the existing `from app.core.deps import get_db`:

```python
from app.core.deps import get_db, verify_n8n_webhook_secret
```

Change the endpoint declaration and signature from:

```python
@router.post("/{document_id}/approval-callback")
async def approval_callback(
    document_id: int,
    payload: ApprovalCallbackRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
):
    """Callback n8n calls after the approval email is answered.

    Treats the email response as the final approval decision (bypasses the
    in-app department -> organization approval chain). Authenticated via a
    shared secret in the X-Webhook-Secret header, matched against
    N8N_CALLBACK_SECRET with a constant-time comparison.
    """
    if not settings.N8N_CALLBACK_SECRET or not x_webhook_secret or not hmac.compare_digest(
        x_webhook_secret, settings.N8N_CALLBACK_SECRET
    ):
        logger.warning(f"Rejected approval-callback call for document {document_id}: invalid webhook secret")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")

    result = await db.execute(select(Document).where(Document.id == document_id))
```

to:

```python
@router.post(
    "/{document_id}/approval-callback",
    dependencies=[Depends(verify_n8n_webhook_secret)],
)
async def approval_callback(
    document_id: int,
    payload: ApprovalCallbackRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Callback n8n calls after the approval email is answered.

    Treats the email response as the final approval decision (bypasses the
    in-app department -> organization approval chain). Authenticated via
    app.core.deps.verify_n8n_webhook_secret (shared secret, X-Webhook-Secret).
    """
    result = await db.execute(select(Document).where(Document.id == document_id))
```

- [ ] **Step 4: Run the same tests again to confirm no regression**

Run: `cd micco-backend/backend && pytest tests/integration/test_approval_callback.py -v`
Expected: all tests still PASS, identical to Step 1.

- [ ] **Step 5: Commit**

```bash
git add micco-backend/backend/app/core/deps.py micco-backend/backend/app/api/documents.py
git commit -m "$(cat <<'EOF'
refactor: extract shared n8n webhook-secret dependency

approval-callback inlined its X-Webhook-Secret check; pulling it into
app.core.deps.verify_n8n_webhook_secret lets the upcoming agent-content
and agent-report endpoints share the same auth without duplicating the
constant-time compare three times.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Lightweight document text extractor

**Files:**
- Create: `micco-backend/backend/app/services/document_text_extractor.py`
- Modify: `micco-backend/backend/requirements.txt`
- Test: `micco-backend/backend/tests/unit/test_document_text_extractor.py`

**Interfaces:**
- Produces: `ExtractedText` dataclass (`supported: bool`, `content: str | None`, `truncated: bool`) and `async def extract_full_text(file_path: Path, file_type: str) -> ExtractedText`, and the constant `AGENT_CONTENT_MAX_CHARS = 20_000`. Consumed by Task 4's `agent-content` endpoint.

- [ ] **Step 1: Add PyMuPDF to requirements**

In `micco-backend/backend/requirements.txt`, under the existing "Document parsing" section, add:

```
PyMuPDF>=1.24.0
```

Run: `cd micco-backend/backend && pip install PyMuPDF>=1.24.0`
Expected: installs cleanly (`import fitz` works — PyMuPDF's import name is `fitz`).

- [ ] **Step 2: Write the failing tests**

Create `micco-backend/backend/tests/unit/test_document_text_extractor.py`:

```python
"""Unit tests for the lightweight (non-NexusRAG) document text extractor.

This is a separate, cheaper code path from app.services.document_parser
(docling/marker) — no LLM calls, plain text only — used by the n8n agent
email-reply endpoints. Everything here runs against real temp files;
nothing external to mock per .claude/rules/testing.md.
"""
from __future__ import annotations

from pathlib import Path

import fitz
from docx import Document as DocxDocument

from app.services.document_text_extractor import (
    AGENT_CONTENT_MAX_CHARS,
    extract_full_text,
)


async def test_extract_full_text_reads_txt_file(tmp_path: Path):
    file_path = tmp_path / "note.txt"
    file_path.write_text("Nội dung ghi chú test.", encoding="utf-8")

    result = await extract_full_text(file_path, "txt")

    assert result.supported is True
    assert result.content == "Nội dung ghi chú test."
    assert result.truncated is False


async def test_extract_full_text_reads_md_file(tmp_path: Path):
    file_path = tmp_path / "note.md"
    file_path.write_text("# Tiêu đề\n\nNội dung.", encoding="utf-8")

    result = await extract_full_text(file_path, "md")

    assert result.supported is True
    assert "Tiêu đề" in result.content


async def test_extract_full_text_reads_docx_paragraphs(tmp_path: Path):
    file_path = tmp_path / "bao_cao.docx"
    doc = DocxDocument()
    doc.add_paragraph("Đoạn một.")
    doc.add_paragraph("Đoạn hai.")
    doc.save(str(file_path))

    result = await extract_full_text(file_path, "docx")

    assert result.supported is True
    assert result.content == "Đoạn một.\nĐoạn hai."


async def test_extract_full_text_reads_pdf_pages(tmp_path: Path):
    file_path = tmp_path / "bao_cao.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Noi dung PDF test.")
    pdf.save(str(file_path))
    pdf.close()

    result = await extract_full_text(file_path, "pdf")

    assert result.supported is True
    assert "Noi dung PDF test." in result.content


async def test_extract_full_text_reports_unsupported_type(tmp_path: Path):
    file_path = tmp_path / "sheet.xlsx"
    file_path.write_bytes(b"not a real xlsx")

    result = await extract_full_text(file_path, "xlsx")

    assert result.supported is False
    assert result.content is None


async def test_extract_full_text_truncates_content_over_the_cap(tmp_path: Path):
    file_path = tmp_path / "long.txt"
    file_path.write_text("a" * (AGENT_CONTENT_MAX_CHARS + 500), encoding="utf-8")

    result = await extract_full_text(file_path, "txt")

    assert result.truncated is True
    assert len(result.content) == AGENT_CONTENT_MAX_CHARS
```

- [ ] **Step 2b: Run tests to verify they fail**

Run: `cd micco-backend/backend && pytest tests/unit/test_document_text_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.document_text_extractor'`

- [ ] **Step 3: Implement the extractor**

Create `micco-backend/backend/app/services/document_text_extractor.py`:

```python
"""Lightweight, on-demand text extraction for the n8n agent email-reply flow.

Deliberately NOT the NexusRAG pipeline (app.services.document_parser —
docling/marker), which calls an LLM to caption every image and table. That's
too slow and costly to run synchronously for an ad-hoc "summarize this"
email reply; this extracts plain text only, nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiofiles
from docx import Document as DocxDocument

AGENT_CONTENT_MAX_CHARS = 20_000

_SUPPORTED_EXTENSIONS = {"txt", "md", "docx", "pdf"}


@dataclass
class ExtractedText:
    supported: bool
    content: str | None
    truncated: bool


async def extract_full_text(file_path: Path, file_type: str) -> ExtractedText:
    """Extract plain text from *file_path*, capped at AGENT_CONTENT_MAX_CHARS."""
    ext = file_type.lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        return ExtractedText(supported=False, content=None, truncated=False)

    if ext in ("txt", "md"):
        async with aiofiles.open(file_path, mode="r", encoding="utf-8", errors="ignore") as f:
            raw = await f.read()
    elif ext == "docx":
        raw = _extract_docx_text(file_path)
    else:
        raw = _extract_pdf_text(file_path)

    truncated = len(raw) > AGENT_CONTENT_MAX_CHARS
    content = raw[:AGENT_CONTENT_MAX_CHARS] if truncated else raw
    return ExtractedText(supported=True, content=content, truncated=truncated)


def _extract_docx_text(file_path: Path) -> str:
    doc = DocxDocument(str(file_path))
    return "\n".join(p.text for p in doc.paragraphs)


def _extract_pdf_text(file_path: Path) -> str:
    import fitz  # PyMuPDF

    with fitz.open(str(file_path)) as pdf:
        return "\n".join(page.get_text() for page in pdf)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd micco-backend/backend && pytest tests/unit/test_document_text_extractor.py -v`
Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add micco-backend/backend/app/services/document_text_extractor.py micco-backend/backend/tests/unit/test_document_text_extractor.py micco-backend/backend/requirements.txt
git commit -m "$(cat <<'EOF'
feat: add lightweight text extractor for n8n agent content endpoint

Plain-text extraction (txt/md/docx/pdf) separate from the NexusRAG
docling/marker pipeline, which is too slow/costly (LLM image+table
captioning) to run synchronously for an ad-hoc email summarization
request. Capped at 20k chars with a truncated flag.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Markdown-to-PDF renderer

**Files:**
- Create: `micco-backend/backend/app/services/agent_pdf.py`
- Create: `micco-backend/backend/app/assets/fonts/DejaVuSans.ttf`
- Create: `micco-backend/backend/app/assets/fonts/DejaVuSans-Bold.ttf`
- Modify: `micco-backend/backend/requirements.txt`
- Test: `micco-backend/backend/tests/unit/test_agent_pdf.py`

**Interfaces:**
- Produces: `def render_markdown_to_pdf(title: str, content_markdown: str) -> bytes`. Consumed by Task 5's `agent-report` endpoint.

- [ ] **Step 1: Add fpdf2 to requirements and copy the Vietnamese-capable font**

In `micco-backend/backend/requirements.txt`, add near the "Utilities" section:

```
fpdf2>=2.7.0
```

Run: `cd micco-backend/backend && pip install fpdf2>=2.7.0`

Copy the font (already present on this machine's system fonts — use it directly; if unavailable, download "DejaVu Sans" from the official DejaVu Fonts project instead):

```bash
mkdir -p micco-backend/backend/app/assets/fonts
cp /usr/share/fonts/TTF/DejaVuSans.ttf micco-backend/backend/app/assets/fonts/DejaVuSans.ttf
cp /usr/share/fonts/TTF/DejaVuSans-Bold.ttf micco-backend/backend/app/assets/fonts/DejaVuSans-Bold.ttf
```

Expected: both files exist under `micco-backend/backend/app/assets/fonts/`.

- [ ] **Step 2: Write the failing test**

Create `micco-backend/backend/tests/unit/test_agent_pdf.py`:

```python
"""Unit tests for rendering an n8n AI Agent's markdown answer to PDF."""
from __future__ import annotations

from app.services.agent_pdf import render_markdown_to_pdf


def test_render_markdown_to_pdf_produces_a_valid_pdf_document():
    pdf_bytes = render_markdown_to_pdf(
        title="Tóm tắt tài liệu",
        content_markdown="# Mục 1\n\nNội dung tóm tắt bằng tiếng Việt có dấu.",
    )

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 0


def test_render_markdown_to_pdf_handles_multiple_paragraphs_and_blank_lines():
    pdf_bytes = render_markdown_to_pdf(
        title="Báo cáo",
        content_markdown="Đoạn một.\n\nĐoạn hai sau dòng trống.",
    )

    assert pdf_bytes.startswith(b"%PDF")
```

- [ ] **Step 2b: Run test to verify it fails**

Run: `cd micco-backend/backend && pytest tests/unit/test_agent_pdf.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.agent_pdf'`

- [ ] **Step 3: Implement the renderer**

Create `micco-backend/backend/app/services/agent_pdf.py`:

```python
"""Render an n8n AI Agent's markdown answer to a PDF for email attachment.

Uses fpdf2 (pure Python, no system libraries like cairo/pango — lighter than
weasyprint for the Docker image) with a bundled Vietnamese-capable font,
since the summarized content is Vietnamese document text.

Not a full markdown renderer: '#'/'##' lines become bold headings, blank
lines become spacing, everything else is a plain paragraph. Good enough for
an LLM-generated summary, not a general-purpose document converter.
"""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_FONT_REGULAR = _FONT_DIR / "DejaVuSans.ttf"
_FONT_BOLD = _FONT_DIR / "DejaVuSans-Bold.ttf"


def render_markdown_to_pdf(title: str, content_markdown: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("DejaVu", "", str(_FONT_REGULAR))
    pdf.add_font("DejaVu", "B", str(_FONT_BOLD))

    pdf.set_font("DejaVu", "B", 16)
    pdf.multi_cell(0, 10, title)
    pdf.ln(4)

    for line in content_markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            pdf.ln(4)
            continue
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            pdf.set_font("DejaVu", "B", 13)
            pdf.multi_cell(0, 8, heading)
        else:
            pdf.set_font("DejaVu", "", 11)
            pdf.multi_cell(0, 7, stripped)

    return bytes(pdf.output())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd micco-backend/backend && pytest tests/unit/test_agent_pdf.py -v`
Expected: both tests PASS

- [ ] **Step 5: Commit**

```bash
git add micco-backend/backend/app/services/agent_pdf.py micco-backend/backend/app/assets/fonts/ micco-backend/backend/tests/unit/test_agent_pdf.py micco-backend/backend/requirements.txt
git commit -m "$(cat <<'EOF'
feat: add markdown-to-PDF renderer for n8n agent report endpoint

fpdf2 + a bundled Vietnamese-capable TTF font, chosen over weasyprint
to avoid adding cairo/pango system dependencies to the Docker image.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `GET /api/v1/documents/{id}/agent-content` endpoint

**Files:**
- Create: `micco-backend/backend/app/api/n8n_agent.py`
- Modify: `micco-backend/backend/app/api/router.py`
- Modify: `micco-backend/backend/tests/conftest.py` (`make_document` fixture)
- Test: `micco-backend/backend/tests/integration/test_n8n_agent_content.py`

**Interfaces:**
- Consumes: `app.core.deps.verify_n8n_webhook_secret` (Task 1), `app.services.document_text_extractor.extract_full_text` + `ExtractedText` (Task 2), `app.api.documents.UPLOAD_DIR`.
- Produces: `router` (an `APIRouter`, prefix `/documents`, tag `n8n-agent`) in `app.api.n8n_agent` — Task 5 adds the `agent-report` endpoint to this same router/file.

- [ ] **Step 0: Let `make_document` accept a `file_type`/`filename` override**

`make_document` in `tests/conftest.py` currently hardcodes both as keyword args to `Document(...)`, so any caller passing `file_type=` or `filename=` today would hit `TypeError: got multiple values for keyword argument`. The new tests below need to control `file_type` (to exercise the txt/unsupported branches), so pull both out of `**columns` first, defaulting to today's values — existing callers that don't pass them are unaffected.

In `micco-backend/backend/tests/conftest.py`, change:

```python
        document = Document(
            workspace_id=workspace_id,
            filename=f"stored_{original_filename}",
            original_filename=original_filename,
            file_type="pdf",
            file_size=1024,
            status=status,
            approval_status=approval_status,
            is_business_visible=is_business_visible,
            **columns,
        )
```

to:

```python
        document = Document(
            workspace_id=workspace_id,
            filename=columns.pop("filename", f"stored_{original_filename}"),
            original_filename=original_filename,
            file_type=columns.pop("file_type", "pdf"),
            file_size=1024,
            status=status,
            approval_status=approval_status,
            is_business_visible=is_business_visible,
            **columns,
        )
```

Run: `cd micco-backend/backend && pytest tests/ -k make_document -v` (and the broader existing suite, e.g. `pytest tests/integration/test_approvals_document.py -v`)
Expected: still PASS — this only changes behavior when `filename`/`file_type` are explicitly passed, which no existing caller does.

- [ ] **Step 1: Write the failing tests**

Create `micco-backend/backend/tests/integration/test_n8n_agent_content.py`:

```python
"""The n8n AI Agent reads a pending document's raw text through this endpoint.

Independent of approval-callback: never touches approval_status. Auth is the
same shared X-Webhook-Secret as approval-callback (app.core.deps).
"""
from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient

from app.core.config import settings
from app.models.document import DocumentStatus

CONTENT_URL = "/api/v1/documents/{document_id}/agent-content"
SECRET = "test-n8n-secret"


def _configure_secret(monkeypatch, secret: str | None = SECRET):
    monkeypatch.setattr(settings, "N8N_CALLBACK_SECRET", secret or "")


async def test_agent_content_rejects_missing_secret_header(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(workspace_id=workspace.id, status=DocumentStatus.PENDING)

    response = await client.get(CONTENT_URL.format(document_id=doc.id))

    assert response.status_code == 401


async def test_agent_content_rejects_wrong_secret(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(workspace_id=workspace.id, status=DocumentStatus.PENDING)

    response = await client.get(
        CONTENT_URL.format(document_id=doc.id),
        headers={"X-Webhook-Secret": "not-the-secret"},
    )

    assert response.status_code == 401


async def test_agent_content_404_for_unknown_document(client: AsyncClient, monkeypatch):
    _configure_secret(monkeypatch)

    response = await client.get(
        CONTENT_URL.format(document_id=999999),
        headers={"X-Webhook-Secret": SECRET},
    )

    assert response.status_code == 404


async def test_agent_content_409_when_document_is_no_longer_pending(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(
        workspace_id=workspace.id, status=DocumentStatus.INDEXED, approval_status="approved"
    )

    response = await client.get(
        CONTENT_URL.format(document_id=doc.id),
        headers={"X-Webhook-Secret": SECRET},
    )

    assert response.status_code == 409


async def test_agent_content_returns_extracted_text_for_pending_txt_document(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(
        workspace_id=workspace.id,
        status=DocumentStatus.PENDING,
        approval_status="pending",
        original_filename="ghi_chu.txt",
        filename="stored_ghi_chu.txt",
        file_type="txt",
    )
    file_path = Path(settings.BASE_DIR) / "uploads" / doc.filename
    file_path.write_text("Nội dung chờ duyệt.", encoding="utf-8")

    try:
        response = await client.get(
            CONTENT_URL.format(document_id=doc.id),
            headers={"X-Webhook-Secret": SECRET},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["supported"] is True
        assert body["content"] == "Nội dung chờ duyệt."
        assert body["truncated"] is False
    finally:
        file_path.unlink(missing_ok=True)


async def test_agent_content_reports_unsupported_file_type(
    client: AsyncClient, make_workspace, make_document, monkeypatch
):
    _configure_secret(monkeypatch)
    workspace = await make_workspace()
    doc = await make_document(
        workspace_id=workspace.id,
        status=DocumentStatus.PENDING,
        approval_status="pending",
        original_filename="bang_gia.xlsx",
        filename="stored_bang_gia.xlsx",
        file_type="xlsx",
    )
    file_path = Path(settings.BASE_DIR) / "uploads" / doc.filename
    file_path.write_bytes(b"not a real xlsx")

    try:
        response = await client.get(
            CONTENT_URL.format(document_id=doc.id),
            headers={"X-Webhook-Secret": SECRET},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["supported"] is False
        assert body["content"] is None
    finally:
        file_path.unlink(missing_ok=True)
```

- [ ] **Step 1b: Run tests to verify they fail**

Run: `cd micco-backend/backend && pytest tests/integration/test_n8n_agent_content.py -v`
Expected: FAIL (route doesn't exist yet — 404s where 401/200/409 expected, or import error)

- [ ] **Step 2: Implement the router and endpoint**

Create `micco-backend/backend/app/api/n8n_agent.py`:

```python
"""n8n AI Agent tool endpoints — email-reply flow for pending documents.

Independent of app.api.documents.approval_callback: these endpoints never
touch approval_status. They let an n8n AI Agent (1) read a pending
document's raw text and (2) render its generated answer as a PDF to attach
to the reply email. Authenticated the same way as approval-callback: a
shared secret in X-Webhook-Secret (see app.core.deps.verify_n8n_webhook_secret).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents import UPLOAD_DIR
from app.core.deps import get_db, verify_n8n_webhook_secret
from app.core.exceptions import ConflictError, NotFoundError
from app.models.document import Document, DocumentStatus
from app.services.document_text_extractor import extract_full_text

router = APIRouter(prefix="/documents", tags=["n8n-agent"])


@router.get(
    "/{document_id}/agent-content",
    dependencies=[Depends(verify_n8n_webhook_secret)],
)
async def get_agent_content(document_id: int, db: AsyncSession = Depends(get_db)):
    """Raw text of a PENDING document, for the n8n AI Agent to reason over."""
    document = (
        await db.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if document is None:
        raise NotFoundError("Document", document_id)

    if document.status != DocumentStatus.PENDING:
        raise ConflictError("Document is no longer pending")

    file_path = UPLOAD_DIR / document.filename
    if not file_path.exists():
        raise NotFoundError("Document file", document_id)

    extracted = await extract_full_text(file_path, document.file_type)

    return {
        "id": document.id,
        "filename": document.original_filename,
        "file_type": document.file_type,
        "supported": extracted.supported,
        "content": extracted.content,
        "truncated": extracted.truncated,
        "message": None if extracted.supported else "Preview not supported for this file type",
    }
```

Register it in `micco-backend/backend/app/api/router.py` — add the import and include it alongside the existing routers:

```python
# before
from app.api.business_chat import router as business_chat_router

api_router = APIRouter()
api_router.include_router(workspaces_router)
api_router.include_router(documents_router)
```

```python
# after
from app.api.business_chat import router as business_chat_router
from app.api.n8n_agent import router as n8n_agent_router

api_router = APIRouter()
api_router.include_router(workspaces_router)
api_router.include_router(documents_router)
api_router.include_router(n8n_agent_router)
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd micco-backend/backend && pytest tests/integration/test_n8n_agent_content.py -v`
Expected: all 6 tests PASS

- [ ] **Step 4: Commit**

```bash
git add micco-backend/backend/app/api/n8n_agent.py micco-backend/backend/app/api/router.py micco-backend/backend/tests/conftest.py micco-backend/backend/tests/integration/test_n8n_agent_content.py
git commit -m "$(cat <<'EOF'
feat: add GET agent-content endpoint for the n8n AI Agent

Lets n8n's AI Agent read a pending document's raw text (via the
lightweight extractor, not the NexusRAG pipeline) so it can answer a
natural-language email reply. Same shared-secret auth as
approval-callback; scoped to PENDING documents only.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `POST /api/v1/documents/{id}/agent-report` endpoint

**Files:**
- Modify: `micco-backend/backend/app/schemas/document.py`
- Modify: `micco-backend/backend/app/api/n8n_agent.py`
- Test: `micco-backend/backend/tests/integration/test_n8n_agent_report.py`

**Interfaces:**
- Consumes: `render_markdown_to_pdf` (Task 3), `router` from `app.api.n8n_agent` (Task 4), `verify_n8n_webhook_secret` (Task 1).
- Produces: `AgentReportRequest` Pydantic schema in `app.schemas.document`.

- [ ] **Step 1: Write the failing tests**

Create `micco-backend/backend/tests/integration/test_n8n_agent_report.py`:

```python
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
```

- [ ] **Step 1b: Run tests to verify they fail**

Run: `cd micco-backend/backend && pytest tests/integration/test_n8n_agent_report.py -v`
Expected: FAIL (404 Not Found — route doesn't exist yet)

- [ ] **Step 2: Add the request schema**

In `micco-backend/backend/app/schemas/document.py`, change the import line and add the new schema at the end:

```python
# before
from pydantic import BaseModel
```
```python
# after
from pydantic import BaseModel, Field
```

Append:

```python
class AgentReportRequest(BaseModel):
    """Body n8n's AI Agent posts to render its drafted answer as a PDF."""

    title: str
    content_markdown: str = Field(min_length=1)
```

- [ ] **Step 3: Add the endpoint to `app/api/n8n_agent.py`**

Add these imports at the top (extend the existing `fastapi` import, add two more):

```python
# before
from fastapi import APIRouter, Depends
```
```python
# after
from fastapi import APIRouter, Depends, Response
```

Add below the existing imports:

```python
from app.schemas.document import AgentReportRequest
from app.services.agent_pdf import render_markdown_to_pdf
```

Append the new endpoint at the end of the file:

```python
@router.post(
    "/{document_id}/agent-report",
    dependencies=[Depends(verify_n8n_webhook_secret)],
)
async def create_agent_report(
    document_id: int,
    payload: AgentReportRequest,
    db: AsyncSession = Depends(get_db),
):
    """Render the AI Agent's drafted markdown answer as a PDF for email attachment."""
    document = (
        await db.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if document is None:
        raise NotFoundError("Document", document_id)

    pdf_bytes = render_markdown_to_pdf(payload.title, payload.content_markdown)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="tai_lieu_{document_id}_tom_tat.pdf"'
        },
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd micco-backend/backend && pytest tests/integration/test_n8n_agent_report.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Run the full backend test suite**

Run: `cd micco-backend/backend && pytest tests/ -x --tb=short`
Expected: all tests PASS (no regressions in `approval-callback`, upload webhook, or any other existing suite)

- [ ] **Step 6: Commit**

```bash
git add micco-backend/backend/app/schemas/document.py micco-backend/backend/app/api/n8n_agent.py micco-backend/backend/tests/integration/test_n8n_agent_report.py
git commit -m "$(cat <<'EOF'
feat: add POST agent-report endpoint to render n8n agent answers as PDF

The n8n AI Agent posts its drafted markdown answer here and gets back a
PDF to attach to the reply email. Pure rendering (fpdf2) — no LLM calls,
no approval_status change, no document-status restriction (only needs
the document to exist).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
