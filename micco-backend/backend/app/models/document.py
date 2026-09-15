from sqlalchemy import String, ForeignKey, DateTime, Integer, Text, Enum, Boolean, JSON, false
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import enum

from app.core.database import Base
from app.models.document_version import DocumentVersion  # noqa: F401


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PARSING = "parsing"
    PROCESSING = "processing"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"
    REJECTED = "rejected"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(50))
    file_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), default=DocumentStatus.PENDING
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Approvals & Access Control
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), default="department") # "internal" | "department" | "public"
    # - "department": chỉ member trong department đọc
    # - "public": tất cả user đọc
    # - "internal": legacy — treated same as "department"
    approval_status: Mapped[str] = mapped_column(String(20), default="pending") # "pending", "approved", "rejected"
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Per-document opt-in for the external B2B portal. Never inferred from the
    # workspace: a file landing in the business workspace stays unpublished
    # until an Admin explicitly publishes it. Read only by
    # app.services.business_rag.get_business_document_ids.
    is_business_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    # Precomputed at upload for the approval notification, so the group chat
    # reads a summary without paying an LLM call per question. Stays NULL when
    # the file type has no extractable text or the LLM was unavailable.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # NexusRAG fields
    markdown_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    table_count: Mapped[int] = mapped_column(Integer, default=0)
    dataset_count: Mapped[int] = mapped_column(Integer, default=0)
    parser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)  # "docling" | "legacy"
    processing_time_ms: Mapped[int] = mapped_column(Integer, default=0)

    # Metadata
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated
    thumbnail: Mapped[str | None] = mapped_column(String(255), nullable=True)  # filename of thumbnail

    # Relationships
    workspace: Mapped["KnowledgeBase"] = relationship(back_populates="documents")
    images: Mapped[list["DocumentImage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    tables: Mapped[list["DocumentTable"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    datasets: Mapped[list["DocumentDataset"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_number.desc()",
    )


class DocumentImage(Base):
    __tablename__ = "document_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    image_id: Mapped[str] = mapped_column(String(100), unique=True)  # UUID
    page_no: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str] = mapped_column(String(500))
    caption: Mapped[str] = mapped_column(Text, default="")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str] = mapped_column(String(50), default="image/png")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    document: Mapped["Document"] = relationship(back_populates="images")


class DocumentTable(Base):
    __tablename__ = "document_tables"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    table_id: Mapped[str] = mapped_column(String(100), unique=True)
    page_no: Mapped[int] = mapped_column(Integer, default=0)
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    num_rows: Mapped[int] = mapped_column(Integer, default=0)
    num_cols: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    document: Mapped["Document"] = relationship(back_populates="tables")


class DocumentDataset(Base):
    """Structured, typed row data extracted from one sheet of a spreadsheet.

    Populated by ``SpreadsheetDocumentParser`` (see
    ``app/services/document_parser/spreadsheet_parser.py``) and consumed by
    the ``aggregate_spreadsheet_data`` chat tool for exact arithmetic over
    spreadsheet data instead of LLM eyeball-summing from retrieved chunks.
    """
    __tablename__ = "document_datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    dataset_id: Mapped[str] = mapped_column(String(100), unique=True)  # UUID
    sheet_name: Mapped[str] = mapped_column(String(255))
    columns: Mapped[list] = mapped_column(JSON)  # [{"name":..., "col_type":..., "unit":...}]
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    rows: Mapped[list] = mapped_column(JSON)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    truncated_at_row: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    document: Mapped["Document"] = relationship(back_populates="datasets")
