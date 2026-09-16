"""Schemas for the external B2B portal (/api/v1/business/...).

This surface follows the response envelope documented in
.claude/rules/api-design.md: {"data": ..., "meta": {...}}.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

DataT = TypeVar("DataT")


class BusinessEnvelope(BaseModel, Generic[DataT]):
    data: DataT
    meta: dict[str, Any] = Field(default_factory=dict)


class BusinessLoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=200)


class BusinessProfile(BaseModel):
    id: int
    company_name: str | None = None
    contact_name: str
    email: str
    phone: str | None = None
    industry: str | None = None
    tax_code: str | None = None
    approval_status: str | None = None


class BusinessLoginData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: BusinessProfile


# ─── Admin: publishing content to the portal ───────────────────────
# These are staff-only (require_admin). They shape what the portal can serve,
# so they live beside the customer schemas they govern.


class WorkspaceAudienceRequest(BaseModel):
    audience: Literal["internal", "business"]


class BusinessWorkspaceSummary(BaseModel):
    id: int
    name: str
    audience: str
    document_count: int = 0
    published_document_count: int = 0


class DocumentPublishRequest(BaseModel):
    is_business_visible: bool


class BusinessDocumentSummary(BaseModel):
    """A document in the business workspace, from the Admin's point of view."""

    id: int
    label: str
    original_filename: str
    status: str
    approval_status: str
    is_business_visible: bool
    is_publishable: bool
    page_count: int = 0
    chunk_count: int = 0
    created_at: datetime | None = None


# ─── Portal chat ───────────────────────────────────────────────────
# Customer-facing. The request is minimal on purpose: extra="forbid" so a
# client that tries to pass workspace_id, document_ids, mode or history gets a
# 422 instead of having it silently ignored. Everything that decides what the
# answer may be grounded in is read on the server.


class BusinessChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=2000)


class BusinessChatSource(BaseModel):
    """A citation as a customer sees it: a label and a page, nothing else.

    No document id, no chunk text, no stored file path. Reading history back
    through this model is what guarantees a row written elsewhere cannot leak
    extra fields.
    """

    label: str
    page_no: int = 0


class BusinessPackageCard(BaseModel):
    """A suggested package as a customer sees it.

    Built from an explicit field list (see business_packages.to_card), so a
    column added to business_packages later cannot reach a customer by default.
    """

    id: int
    name: str
    category: str
    summary: str
    target_customer: str | None = None
    highlights: list[str] = Field(default_factory=list)
    price_note: str | None = None


class BusinessChatMessage(BaseModel):
    message_id: str
    role: str
    content: str
    sources: list[BusinessChatSource] = Field(default_factory=list)
    recommendations: list[BusinessPackageCard] = Field(default_factory=list)
    created_at: datetime | None = None


class BusinessChatHistoryData(BaseModel):
    messages: list[BusinessChatMessage] = Field(default_factory=list)
    total: int = 0


class BusinessChatCleared(BaseModel):
    deleted: int = 0


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
