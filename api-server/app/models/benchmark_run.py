"""Persistence for an immutable, Order-linked blind benchmark run.

BenchmarkRun stores only a sanitized context snapshot.  The source Order keeps
its ordinary analysis context unchanged and is never used as a report/LLM
context for the blind run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.mysql import DATETIME as DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


BENCHMARK_RUN_STATUS = (
    "registered",
    "snapshot_pending",
    "preprocessing",
    "temporal_analysis",
    "scoring_queued",
    "scoring",
    "completed",
    "failed",
    "cancelled",
)


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    __table_args__ = (
        Index("ix_benchmark_runs_source_order_id_created_at", "source_order_id", "created_at"),
        Index("ix_benchmark_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    benchmark_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    dataset_id: Mapped[str] = mapped_column(String(120), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    production_contract: Mapped[dict] = mapped_column(JSON, nullable=False)
    blind_policy: Mapped[dict] = mapped_column(JSON, nullable=False)
    blind_context: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)

    status: Mapped[str] = mapped_column(
        Enum(*BENCHMARK_RUN_STATUS, name="benchmark_run_status"),
        default="registered",
        nullable=False,
    )
    artifact_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    result_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    score_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    provenance: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
