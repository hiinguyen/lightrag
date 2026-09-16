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
