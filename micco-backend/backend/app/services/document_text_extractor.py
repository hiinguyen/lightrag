"""Lightweight, on-demand text extraction for the n8n agent email-reply flow.

Deliberately NOT the NexusRAG pipeline (app.services.document_parser —
docling/marker), which calls an LLM to caption every image and table. That's
too slow and costly to run synchronously for an ad-hoc "summarize this"
email reply; this extracts plain text only, nothing else.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import aiofiles
from docx import Document as DocxDocument

logger = logging.getLogger(__name__)

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
        try:
            raw = await asyncio.to_thread(_extract_docx_text, file_path)
        except Exception:
            logger.warning(f"Failed to extract docx text from {file_path}", exc_info=True)
            return ExtractedText(supported=False, content=None, truncated=False)
    else:
        try:
            raw = await asyncio.to_thread(_extract_pdf_text, file_path)
        except Exception:
            logger.warning(f"Failed to extract pdf text from {file_path}", exc_info=True)
            return ExtractedText(supported=False, content=None, truncated=False)

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
