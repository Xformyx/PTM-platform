from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    report_type: Mapped[str] = mapped_column(
        Enum(
            "preprocessing_summary",
            "rag_enrichment",
            "comprehensive",
            "qa",
            "publication_qa",
            name="report_type",
        ),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_format: Mapped[str] = mapped_column(
        Enum("md", "pdf", "docx", "tsv", name="report_format"), nullable=False
    )
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    llm_model_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("llm_models.id", ondelete="SET NULL"), nullable=True
    )
    generation_time_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quality_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(3, 2), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    order: Mapped["Order"] = relationship(back_populates="reports")
