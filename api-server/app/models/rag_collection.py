from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RagCollection(Base):
    __tablename__ = "rag_collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tier: Mapped[str] = mapped_column(
        Enum("cell_type", "ptm_type", "pathway", "general", name="collection_tier"),
        nullable=False,
    )
    chromadb_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    embedding_model: Mapped[str] = mapped_column(
        String(255), default="all-MiniLM-L6-v2"
    )
    chunk_strategy: Mapped[str] = mapped_column(
        Enum("fixed", "semantic", "recursive", name="chunk_strategy"),
        default="recursive",
    )
    chunk_size: Mapped[int] = mapped_column(Integer, default=1000)
    document_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    documents: Mapped[list["RagDocument"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )


class RagDocument(Base):
    __tablename__ = "rag_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rag_collections.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(
        Enum("pdf", "md", "txt", "csv", name="doc_file_type"), nullable=False
    )
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "indexed", "failed", name="doc_status"),
        default="pending",
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    collection: Mapped["RagCollection"] = relationship(back_populates="documents")
