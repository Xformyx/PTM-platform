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

    # Search parameters (added in v0.5.2 — enzyme & Orbitrap instrument preset)
    enzyme: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    instrument: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # diaquant `--engine sage` vs default AlphaDIA (`alphadia`); synced from config/env at run start.
    search_engine: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # AlphaPeptDeep options (added in v0.5.2). Stored as TINYINT(1) in MySQL.
    predicted_library: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transfer_learning: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Phospho localization filter (v0.5.3).  site_probability_cutoff is the
    # minimum Best.Site.Probability kept in report.ptm_site_matrix.tsv; when
    # include_low_loc_sites is True every site is reported and downstream
    # consumers filter on the per-row probability column.
    site_probability_cutoff: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    include_low_loc_sites: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # AlphaDIA library_prediction.max_var_mod_num override (default 2; diaquant phospho pass
    # internally raises this to 3 which causes ~47M precursors and PeptDeep OOM crash).
    max_var_mod_num: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # missed_cleavages override (default 1; diaquant phospho pass uses 2 which doubles
    # speclib size → DecoyGenerator OOM crash on large proteomes).
    missed_cleavages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # pred_lib_max_precursors: hard upper bound on digested precursor count passed to
    # diaquant (env PTMQUANT_PEPTDEEP_MAX_PRECURSORS / config key pred_lib_max_precursors).
    max_precursors: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # alphadia_threads: AlphaDIA general.thread_count (PTMQUANT_ALPHADIA_THREADS env var).
    # Each worker holds a copy of the speclib → peak RAM ≈ N × per-thread-speclib-size.
    # Auto-calculated from max_memory_gb: ≤64GB→2, ≤96GB→4, ≤128GB→6, >128GB→0(auto).
    alphadia_threads: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

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
