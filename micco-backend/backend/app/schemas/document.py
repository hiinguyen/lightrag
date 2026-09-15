from pydantic import BaseModel, Field
from datetime import datetime
from app.models.document import DocumentStatus


class DocumentBase(BaseModel):
    filename: str
    original_filename: str
    file_type: str
    file_size: int


class DocumentCreate(DocumentBase):
    workspace_id: int


class DocumentUpdate(BaseModel):
    original_filename: str


class DocumentResponse(DocumentBase):
    id: int
    workspace_id: int
    status: DocumentStatus
    chunk_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    # NexusRAG fields
    page_count: int = 0
    image_count: int = 0
    table_count: int = 0
    parser_version: str | None = None
    processing_time_ms: int = 0
    # RBAC / approval fields
    uploader_id: int | None = None
    department_id: int | None = None
    visibility: str = "internal"
    approval_status: str = "approved"

    model_config = {"from_attributes": True}


class DocumentUploadResponse(BaseModel):
    id: int
    filename: str
    status: DocumentStatus
    message: str


class ApprovalCallbackRequest(BaseModel):
    """Body n8n posts back after the approval email is answered."""

    approved: bool
    note: str | None = None


class AgentReportRequest(BaseModel):
    """Body n8n's AI Agent posts to render its drafted answer as a PDF."""

    title: str = Field(max_length=500)
    content_markdown: str = Field(min_length=1, max_length=100_000)
