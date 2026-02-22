from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import DATETIME as DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

ORDER_STATUS = (
    "pending",
    "queued",
    "preprocessing",
    "rag_enrichment",
    "report_generation",
    "completed",
    "failed",
    "cancelled",
)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(*ORDER_STATUS, name="order_status"), default="pending"
    )
    priority: Mapped[int] = mapped_column(Integer, default=5)

    # Sample info
    ptm_type: Mapped[str] = mapped_column(
        Enum("phosphorylation", "ubiquitination", name="ptm_type"), nullable=False
    )
    species: Mapped[str] = mapped_column(String(50), nullable=False)
    organism_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sample_config: Mapped[dict] = mapped_column(JSON, nullable=False)

    # File references
    pr_matrix_path: Mapped[str] = mapped_column(String(500), nullable=False)
    pg_matrix_path: Mapped[str] = mapped_column(String(500), nullable=False)
    fasta_path: Mapped[str] = mapped_column(String(500), nullable=False)
    config_xlsx_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Analysis settings
    analysis_context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    analysis_options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    report_options: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Progress
    current_stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    progress_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    stage_detail: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Results
    result_files: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    logs: Mapped[list["OrderLog"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    reports: Mapped[list["Report"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderLog(Base):
    __tablename__ = "order_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    step: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("started", "running", "progress", "completed", "failed", "skipped", name="log_status"),
        nullable=False,
    )
    progress_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(fsp=3), server_default=func.now()
    )

    order: Mapped["Order"] = relationship(back_populates="logs")
