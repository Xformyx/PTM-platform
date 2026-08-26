from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import DATETIME as DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

ORDER_STATUS = (
    "registered",
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
    order_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    run_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(*ORDER_STATUS, name="order_status"), default="registered"
    )
    priority: Mapped[int] = mapped_column(Integer, default=5)

    # Sample info
    ptm_type: Mapped[str] = mapped_column(
        Enum("phosphorylation", "ubiquitylation", "ubiquitination", name="ptm_type"), nullable=False  # ubiquitination kept for backward compat
    )
    species: Mapped[str] = mapped_column(String(50), nullable=False)
    organism_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sample_config: Mapped[dict] = mapped_column(JSON, nullable=False)

    # File references
    pr_matrix_path: Mapped[str] = mapped_column(String(500), nullable=False)
    pg_matrix_path: Mapped[str] = mapped_column(String(500), nullable=False)
    fasta_path: Mapped[str] = mapped_column(String(500), nullable=False)
    config_xlsx_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Secondary file references (Cross-Talk mode)
    secondary_pr_matrix_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    secondary_pg_matrix_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    secondary_ptm_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g. "ubiquitylation", "phosphorylation"
    secondary_sample_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # Sample config for secondary PTM dataset

    # Analysis settings
    analysis_context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    analysis_options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    report_options: Mapped[dict] = mapped_column(JSON, nullable=False)

    # RAG collection selection (list of collection IDs; null = use all active)
    rag_collections: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Progress
    current_stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    progress_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    stage_detail: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Results
    result_files: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Cross-Talk analysis data (JSON)
    # {primarySummary, secondarySummary, dualPTMProteins, gatingEvents, sharedNonPTM, ...}
    cross_talk_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Signal Propagation Timeline data (JSON)
    # {mode, ptm_type, timepoints, nonptm_effectors, self_timelags, cascade_timelags, summary}
    signal_propagation_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Kinase Analysis data (JSON) — saved from Global Kinase Modules frontend analysis
    # {kinase_modules, temporal_cascade, cowave_cross_analysis, summary,
    #  temporal_ptm_protein_analysis (shared v2 compact sidecar projection), saved_at}
    kinase_analysis_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Receptor Inference data (JSON) — saved from vector-plot-data endpoint
    # [{name, receptor_class, downstream_ptm_count, downstream_ptms, via_kinases, source, ...}]
    receptor_inference_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # IP Overlay data (JSON) — immunoprecipitation cross-reference results
    # {bait, condition, prey_proteins: [{gene, log2fc, q_value, ...}], cross_reference: {...}, saved_at}
    ip_overlay_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Kinase Activity Temporal Heatmap data (JSON) — computed from vector_data + kinase_modules
    # {kinase_scores: [{kinase, conditions, scores, substrate_count, confidence}], conditions, _cache_hash}
    kinase_activity_heatmap: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # GO Cellular Component localization data (JSON) — fetched from UniProt
    # {gene_localizations: {GENE: ["nucleus", "cytoplasm", ...]}, summary: {term: count}, fetched_at}
    substrate_go_localization: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Watchdog
    watchdog_alerted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    watchdog_restart_count: Mapped[int] = mapped_column(Integer, default=0)

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

    __table_args__ = (
        Index("ix_order_logs_order_id_id", "order_id", "id"),
    )


class OrderShare(Base):
    """Tracks which orders have been shared with which users and at what access level."""
    __tablename__ = "order_shares"
    __table_args__ = (
        UniqueConstraint("order_id", "shared_with_user_id", name="uq_order_share"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    shared_with_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    access_level: Mapped[str] = mapped_column(
        Enum("full_access", "read_only", name="share_access_level"),
        nullable=False,
        default="read_only",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
