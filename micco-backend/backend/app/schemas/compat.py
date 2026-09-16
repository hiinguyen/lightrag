from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import BaseModel


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    department_id: int | None = None


class BusinessRegisterRequest(BaseModel):
    company_name: str
    contact_name: str
    email: str
    password: str
    phone: str
    tax_code: str | None = None
    industry: str | None = None


class BusinessRegisterResponse(BaseModel):
    message: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    department_id: int | None = None
    department_name: str | None = None
    avatar: str | None = None


class UserUpdateRequest(BaseModel):
    name: str | None = None
    password: str | None = None


class DepartmentResponse(BaseModel):
    id: int
    name: str
    description: str | None = None


class LegacyChatSendRequest(BaseModel):
    message: str
    document_ids: list[int] = []


class LegacyChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    sources: list[str] = []
    graph_data: dict | None = None


class KnowledgeCreateRequest(BaseModel):
    title: str
    content_html: str
    content_text: str
    category: str = "Chung"
    tags: list[str] = []
    visibility: str = "internal"
    status: str = "Active"


class KnowledgeUpdateRequest(BaseModel):
    title: str | None = None
    content_html: str | None = None
    content_text: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    visibility: str | None = None
    status: str | None = None


class LegacyDocumentVersionResponse(BaseModel):
    id: int
    document_id: int
    version_number: int
    version_label: str
    filename: str | None = None
    size: str | None = None
    change_note: str | None = None
    created_by_name: str = "System"
    is_current: bool = True
    created_at: datetime


# ─── User Management Schemas ──────────────────────────────────────

class AdminCreateUserRequest(BaseModel):
    name: str
    email: str
    password: str | None = None
    role: str = "Nhân viên"
    department_id: int | None = None


class AdminUpdateUserRequest(BaseModel):
    name: str | None = None
    email: str | None = None
    role: str | None = None
    department_id: int | None = None
    password: str | None = None


class AdminUserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    department_id: int | None = None
    department_name: str | None = None
    avatar: str | None = None
    created_at: datetime | None = None
    approval_status: str | None = None
    # Business account fields — shown when an admin reviews a "Doanh nghiệp"
    # signup; null for internal roles.
    company_name: str | None = None
    tax_code: str | None = None
    phone: str | None = None
    industry: str | None = None

    @classmethod
    def from_user(cls, user) -> "AdminUserResponse":
        return cls(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            department_id=user.department_id,
            department_name=user.department.name if user.department else None,
            avatar=user.avatar,
            created_at=user.created_at,
            approval_status=user.approval_status,
            company_name=user.company_name,
            tax_code=user.tax_code,
            phone=user.phone,
            industry=user.industry,
        )


class AdminApproveBusinessRequest(BaseModel):
    approval_status: Literal["approved", "rejected"]


class AdminListUsersResponse(BaseModel):
    users: list[AdminUserResponse]
    total: int
    page: int
    page_size: int


# ─── Department Schemas ────────────────────────────────────────────

class DepartmentCreateRequest(BaseModel):
    name: str
    description: str | None = None


class DepartmentUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class DepartmentResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    created_at: datetime | None = None
    user_count: int = 0


# ─── Processing Status Schemas ─────────────────────────────────────

class ProcessingStatusResponse(BaseModel):
    id: int
    name: str
    status: str
    # Needed alongside `status`: a failed document is handed back to the
    # approval queue, so the UI has to tell "chờ duyệt" apart from "xử lý lỗi".
    approval_status: str
    chunk_count: int
    error_message: str | None = None
    uploader_name: str
    department_name: str | None = None
    created_at: datetime
    file_type: str | None = None
    file_size: int = 0


class StatusCounts(BaseModel):
    all: int = 0
    pending: int = 0
    processing: int = 0
    indexed: int = 0
    failed: int = 0


class ProcessingStatusListResponse(BaseModel):
    items: list[ProcessingStatusResponse]
    total: int
    counts: StatusCounts = StatusCounts()
