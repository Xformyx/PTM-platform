from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.mysql import DATETIME as DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

PTMQUANT_STATUS = ("pending", "running", "done", "failed", "cancelled")


class PTMQuantJob(Base):
    __tablename__ = "ptmquant_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    reference_file: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    input_files: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    passes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    output_subdir: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    progress: Mapped[float] = mapped_column(Float, default=0.0)
    log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(fsp=3), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(fsp=3), server_default=func.now(), onupdate=func.now()
    )
