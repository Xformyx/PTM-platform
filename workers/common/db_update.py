import json
import logging
import os

from sqlalchemy import text

from common.db_engine import get_engine as _get_engine


logger = logging.getLogger("ptm-workers.db")


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


_PIPELINE_STAGES = {"preprocessing", "rag_enrichment", "report_generation"}


def update_order_status(
    order_id: int,
    status: str | None,
    current_stage: str | None = None,
    progress_pct: float | None = None,
    error_message: str | None = None,
    result_files: dict | None = None,
    report_options_merge: dict | None = None,
    stage_detail: str | None = None,
):
    try:
        existing = get_order_status(order_id)
        if existing == "cancelled":
            # User stopped the job — do not let pipeline workers overwrite status/stage.
            if status is None:
                return
            if status in _PIPELINE_STAGES:
                return
            # Keep cancelled; do not mark failed/completed from a late worker exception.
            if status in ("failed", "completed"):
                return

        engine = _get_engine()
        sets = []
        params: dict = {"order_id": order_id}

        if status is not None:
            sets.append("status = :status")
            params["status"] = status

        if current_stage is not None:
            sets.append("current_stage = :current_stage")
            params["current_stage"] = current_stage
            # Sync status to match current_stage for pipeline stages
            if current_stage in _PIPELINE_STAGES and status is None:
                sets.append("status = :status")
                params["status"] = current_stage

        if progress_pct is not None:
            sets.append("progress_pct = :progress_pct")
            params["progress_pct"] = progress_pct
        if error_message is not None:
            sets.append("error_message = :error_message")
            params["error_message"] = error_message[:2000]
        if result_files is not None:
            sets.append("result_files = :result_files")
            params["result_files"] = json.dumps(result_files)
        if stage_detail is not None:
            sets.append("stage_detail = :stage_detail")
            params["stage_detail"] = stage_detail[:255]

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
            if progress_pct is None:
                sets.append("progress_pct = 100")
            if current_stage is None:
                sets.append("current_stage = 'completed'")
            if stage_detail is None:
                sets.append("stage_detail = 'Completed'")
        if status == "failed":
            sets.append("completed_at = NOW()")
            if stage_detail is None and error_message is not None:
                sets.append("stage_detail = :_fail_detail")
                params["_fail_detail"] = f"Failed: {error_message[:200]}"

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
        if get_order_status(order_id) == "cancelled":
            return

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
            if current_stage in _PIPELINE_STAGES:
                sets.append("status = :status")
                params["status"] = current_stage
        sql = text(f"UPDATE orders SET {', '.join(sets)} WHERE id = :order_id")
        with engine.connect() as conn:
            conn.execute(sql, params)
            conn.commit()
    except Exception as e:
        logger.warning(f"[Order {order_id}] Failed to update progress: {e}")


def update_watchdog_alert(order_id: int, stage_detail: str):
    """Set watchdog_alerted_at to NOW() and update stage_detail."""
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE orders SET watchdog_alerted_at = NOW(), "
                    "stage_detail = :detail WHERE id = :order_id"
                ),
                {"order_id": order_id, "detail": stage_detail[:255]},
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[Order {order_id}] Failed to update watchdog alert: {e}")


def increment_watchdog_restart(order_id: int) -> int:
    """Increment watchdog_restart_count and return new value."""
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE orders SET watchdog_restart_count = watchdog_restart_count + 1, "
                    "watchdog_alerted_at = NOW() WHERE id = :order_id"
                ),
                {"order_id": order_id},
            )
            conn.commit()
            row = conn.execute(
                text("SELECT watchdog_restart_count FROM orders WHERE id = :order_id"),
                {"order_id": order_id},
            ).fetchone()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.warning(f"[Order {order_id}] Failed to increment restart count: {e}")
        return 99


def reset_watchdog(order_id: int):
    """Clear watchdog state when an order starts a new stage normally."""
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE orders SET watchdog_alerted_at = NULL, "
                    "watchdog_restart_count = 0 WHERE id = :order_id"
                ),
                {"order_id": order_id},
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[Order {order_id}] Failed to reset watchdog: {e}")


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
