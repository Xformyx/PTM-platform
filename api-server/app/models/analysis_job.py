"""Production TMM job state survives Celery result expiry and API restarts."""
from sqlalchemy import Integer, String, JSON, DateTime, Boolean, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_revision: Mapped[str] = mapped_column(String(64))
    input_signature: Mapped[str] = mapped_column(String(64), index=True)
    active_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    generation: Mapped[int] = mapped_column(Integer)
    attempt_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    execution_status: Mapped[str] = mapped_column(String(24), default="queued")
    evaluation_status: Mapped[str] = mapped_column(String(24), default="not_evaluable")
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    heartbeat_at = mapped_column(DateTime, nullable=True)
    recovery_count: Mapped[int] = mapped_column(Integer, default=0)
    request_config: Mapped[dict] = mapped_column(JSON, default=dict)
    stage_status: Mapped[dict] = mapped_column(JSON, default=dict)
    result_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    result_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at = mapped_column(DateTime, server_default=func.now())
    updated_at = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AnalysisHead(Base):
    __tablename__ = "analysis_heads"
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.id"), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    requested_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
