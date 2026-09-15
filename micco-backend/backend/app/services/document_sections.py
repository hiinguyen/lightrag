"""Split an extracted document into sections the agent can address by index.

Answers "tóm tắt phần điều khoản thanh toán" without embeddings, so it works
on a PENDING document that the RAG pipeline has not indexed yet — and without
shipping the whole file into a prompt just to reach one clause.

Detection is structural, not semantic: a heading is a short line matching a
Vietnamese document convention (PHẦN / CHƯƠNG / MỤC / Điều N / numbered
clauses) or markdown. The length guard is what keeps a sentence that merely
opens with "Điều này..." from being mistaken for a heading.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_HEADING_CHARS = 120

_HEADING_PATTERNS = (
    re.compile(r"^#{1,6}\s+\S"),
    re.compile(r"^(PHẦN|CHƯƠNG|MỤC)\s+[IVXLCDM\d]", re.IGNORECASE),
    re.compile(r"^ĐIỀU\s+\d+", re.IGNORECASE),
    re.compile(r"^\d+(\.\d+)*[.)]\s+\S"),
    re.compile(r"^\d+\.\d+\s+\S"),
)


@dataclass
class Section:
    heading: str | None
    content: str


def split_into_sections(text: str) -> list[Section]:
    """Split *text* on its headings, keeping each heading with its own body."""
    if not text or not text.strip():
        return []

    sections: list[Section] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if buffer and "\n".join(buffer).strip():
            sections.append(Section(heading=heading, content="\n".join(buffer).strip()))

    for line in text.splitlines():
        if _is_heading(line):
            flush()
            heading = line.strip()
            buffer = [line]
        else:
            buffer.append(line)

    flush()
    return sections


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > MAX_HEADING_CHARS:
        return False
    return any(pattern.match(stripped) for pattern in _HEADING_PATTERNS)
