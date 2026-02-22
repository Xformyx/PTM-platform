import json
import logging
import os

from sqlalchemy import create_engine, text

logger = logging.getLogger("ptm-workers.db")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+asyncmy://ptm_user:ptm_password@localhost:3306/ptm_platform",
)
SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncmy", "+pymysql").replace("+aiomysql", "+pymysql")


def _get_engine():
    return create_engine(SYNC_DATABASE_URL, pool_pre_ping=True, pool_size=2)


def get_order_status(order_id: int) -> str | None:
    """Return the current status of an order. Returns None if not found."""
    try:
        engine = _get_engine()
        row = None
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT status FROM orders WHERE id = :order_id"),
                {"order_id": order_id},
            ).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.warning(f"[Order {order_id}] Failed to get status: {e}")
        return None


def update_order_status(
    order_id: int,
    status: str | None,
    current_stage: str | None = None,
    progress_pct: float | None = None,
    error_message: str | None = None,
    result_files: dict | None = None,
    report_options_merge: dict | None = None,
):
    try:
        engine = _get_engine()
        sets = []
        params: dict = {"order_id": order_id}

        if status is not None:
            sets.append("status = :status")
            params["status"] = status

        if current_stage is not None:
            sets.append("current_stage = :current_stage")
            params["current_stage"] = current_stage
        if progress_pct is not None:
            sets.append("progress_pct = :progress_pct")
            params["progress_pct"] = progress_pct
        if error_message is not None:
            sets.append("error_message = :error_message")
            params["error_message"] = error_message[:2000]
        if result_files is not None:
            sets.append("result_files = :result_files")
            params["result_files"] = json.dumps(result_files)

        if report_options_merge is not None:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT report_options FROM orders WHERE id = :order_id"),
                    {"order_id": order_id},
                ).fetchone()
                existing = json.loads(row[0]) if row and row[0] else {}
                existing.update(report_options_merge)
                sets.append("report_options = :report_options")
                params["report_options"] = json.dumps(existing)

        if status == "completed":
            sets.append("completed_at = NOW()")
        if status == "failed":
            sets.append("completed_at = NOW()")

        if not sets:
            return

        sql = f"UPDATE orders SET {', '.join(sets)} WHERE id = :order_id"
        with engine.connect() as conn:
            conn.execute(text(sql), params)
            conn.commit()

        logger.info(f"[Order {order_id}] DB status → {status}")
    except Exception as e:
        logger.warning(f"[Order {order_id}] Failed to update DB status: {e}")


def update_order_progress(
    order_id: int,
    progress_pct: float,
    stage_detail: str = "",
    current_stage: str | None = None,
):
    """Update progress_pct, stage_detail, and optionally current_stage in orders table."""
    try:
        engine = _get_engine()
        sets = ["progress_pct = :pct", "stage_detail = :detail"]
        params: dict = {
            "order_id": order_id,
            "pct": round(progress_pct, 1),
            "detail": (stage_detail or "")[:255],
        }
        if current_stage is not None:
            sets.append("current_stage = :current_stage")
            params["current_stage"] = current_stage
        sql = text(f"UPDATE orders SET {', '.join(sets)} WHERE id = :order_id")
        with engine.connect() as conn:
            conn.execute(sql, params)
            conn.commit()
    except Exception as e:
        logger.warning(f"[Order {order_id}] Failed to update progress: {e}")


def insert_order_log(
    order_id: int,
    stage: str,
    step: str,
    status: str,
    progress_pct: float | None = None,
    message: str = "",
    metadata: dict | None = None,
    duration_ms: int | None = None,
):
    try:
        engine = _get_engine()
        sql = text(
            "INSERT INTO order_logs "
            "(order_id, stage, step, status, progress_pct, message, metadata, duration_ms) "
            "VALUES (:order_id, :stage, :step, :status, :progress_pct, :message, :metadata, :duration_ms)"
        )
        params = {
            "order_id": order_id,
            "stage": stage,
            "step": step,
            "status": status,
            "progress_pct": progress_pct,
            "message": (message or "")[:2000],
            "metadata": json.dumps(metadata) if metadata else None,
            "duration_ms": duration_ms,
        }
        with engine.connect() as conn:
            conn.execute(sql, params)
            conn.commit()
    except Exception as e:
        logger.warning(f"[Order {order_id}] Failed to insert log: {e}")
