"""
Watchdog — periodic Celery Beat task that detects stalled / halted analyses.

Detection strategy (2-stage to avoid false positives):
  1. Identify orders with active status (preprocessing / rag_enrichment / report_generation)
  2. For each, check:
     a. Whether an active Celery task exists for this order (inspect.active)
     b. Whether order_logs received any new entry within the stall threshold
     c. Whether DB progress_pct changed in the last check window
  3. If both (a) no active task AND (b) no recent log → likely stalled.
     If (a) task exists but (b+c) no progress for extended time → likely hung.

Thresholds are generous to avoid false positives with long LLM calls:
  - WATCHDOG_NO_TASK_STALL_MINUTES:  minutes with no active Celery task (default: 15)
  - WATCHDOG_NO_PROGRESS_STALL_MINUTES: minutes with zero log/progress updates (default: 60)
  - WATCHDOG_ALERT_COOLDOWN_MINUTES: cooldown between repeated alerts for same order (default: 120)
  - WATCHDOG_MAX_RESTARTS: max auto-restart attempts before halting (default: 2)
"""

import logging
from datetime import datetime, timedelta, timezone

from celery import current_app
from sqlalchemy import text

from common.db_engine import get_engine as _get_engine
from common.db_update import (
    update_order_status,
    update_watchdog_alert,
    increment_watchdog_restart,
)
from common.notifications import notify_watchdog_alert
from common.system_settings import get_int, get_bool

logger = logging.getLogger("ptm-workers.watchdog")

ACTIVE_STATUSES = ("preprocessing", "rag_enrichment", "report_generation")

TASK_NAME_MAP = {
    "preprocessing": "preprocessing.tasks.run_preprocessing",
    "rag_enrichment": "rag_enrichment.tasks.run_rag_enrichment",
    "report_generation": "report_generation.tasks.run_report_generation",
}

STAGE_LOCK_KEYS = {
    "report_generation": "report_gen_lock:{order_id}",
}


def _get_active_orders() -> list[dict]:
    """Fetch orders currently in an active analysis stage."""
    engine = _get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, order_code, status, current_stage, progress_pct, "
                "stage_detail, watchdog_alerted_at, watchdog_restart_count, started_at "
                "FROM orders WHERE status IN :statuses"
            ),
            {"statuses": ACTIVE_STATUSES},
        ).fetchall()
    return [
        {
            "id": r[0],
            "order_code": r[1],
            "status": r[2],
            "current_stage": r[3],
            "progress_pct": float(r[4]) if r[4] is not None else 0,
            "stage_detail": r[5],
            "watchdog_alerted_at": r[6],
            "watchdog_restart_count": int(r[7]) if r[7] is not None else 0,
            "started_at": r[8],
        }
        for r in rows
    ]


def _get_latest_log_time(order_id: int) -> datetime | None:
    """Return the timestamp of the most recent order_log entry."""
    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT MAX(created_at) FROM order_logs WHERE order_id = :oid"
            ),
            {"oid": order_id},
        ).fetchone()
    return row[0] if row and row[0] else None


def _get_celery_active_order_ids() -> set[int]:
    """
    Query Celery workers for currently executing tasks and extract order_ids.
    Returns set of order_ids that have at least one active Celery task.
    """
    active_ids: set[int] = set()
    try:
        inspector = current_app.control.inspect(timeout=5.0)
        active = inspector.active()
        if not active:
            return active_ids
        for worker_name, tasks in active.items():
            for task in tasks:
                args = task.get("args")
                if args and isinstance(args, (list, tuple)) and len(args) >= 1:
                    try:
                        active_ids.add(int(args[0]))
                    except (ValueError, TypeError):
                        pass
        logger.debug(f"Celery active order IDs: {active_ids}")
    except Exception as e:
        logger.warning(f"Watchdog: failed to inspect Celery workers: {e}")
    return active_ids


def _is_in_cooldown(alerted_at: datetime | None) -> bool:
    """Check if the order is still within the alert cooldown window."""
    if alerted_at is None:
        return False
    cooldown_min = get_int("WATCHDOG_ALERT_COOLDOWN_MINUTES", 120)
    now_utc = datetime.now(timezone.utc)
    alerted_utc = alerted_at.replace(tzinfo=timezone.utc) if alerted_at.tzinfo is None else alerted_at
    return (now_utc - alerted_utc) < timedelta(minutes=cooldown_min)


def _clear_stale_locks(order_id: int) -> int:
    """Remove Redis stage-execution locks for the given order."""
    import redis as _redis
    import os
    redis_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
    r = _redis.from_url(redis_url, decode_responses=True)
    cleared = 0
    for pattern in STAGE_LOCK_KEYS.values():
        key = pattern.format(order_id=order_id)
        if r.delete(key):
            cleared += 1
    if cleared:
        logger.info(f"[Watchdog] Cleared {cleared} stale lock(s) for order {order_id}")
    return cleared


def _handle_stalled_order(order: dict, reason: str):
    """Take action on a stalled order: notify, optionally restart or halt."""
    order_id = order["id"]
    stage = order["status"]
    restart_count = order["watchdog_restart_count"]
    auto_restart = get_bool("WATCHDOG_AUTO_RESTART", False)
    max_restarts = get_int("WATCHDOG_MAX_RESTARTS", 2)

    _clear_stale_locks(order_id)

    logger.warning(
        f"[Watchdog] Order {order_id} ({order['order_code']}) stalled at "
        f"'{stage}' — {reason}"
    )

    if auto_restart and restart_count < max_restarts:
        new_count = increment_watchdog_restart(order_id)
        logger.info(
            f"[Watchdog] Auto-restarting order {order_id} "
            f"(attempt {new_count}/{max_restarts})"
        )
        _restart_stage(order_id, stage)
        notify_watchdog_alert(
            order_id, reason, stage, action_taken="auto_restart"
        )
    else:
        detail = f"Halted: {reason}"
        update_watchdog_alert(order_id, detail)
        action = "halted" if auto_restart else "none"
        notify_watchdog_alert(
            order_id, reason, stage, action_taken=action
        )


def _restart_stage(order_id: int, stage: str):
    """
    Dispatch a fresh Celery task for the stalled stage.
    Rebuilds a minimal config from the DB order row.
    """
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT order_code, analysis_options, result_files "
                    "FROM orders WHERE id = :oid"
                ),
                {"oid": order_id},
            ).fetchone()
        if not row:
            logger.error(f"[Watchdog] Cannot restart order {order_id}: not found")
            return

        import json
        order_code = row[0]
        analysis_opts = json.loads(row[1]) if row[1] else {}
        result_files = json.loads(row[2]) if row[2] else {}

        task_name = TASK_NAME_MAP.get(stage)
        if not task_name:
            logger.error(f"[Watchdog] Unknown stage '{stage}' for restart")
            return

        config = {
            "order_code": order_code,
            "restart_by_watchdog": True,
            **result_files,
            **analysis_opts,
        }

        update_order_status(order_id, stage, current_stage=stage, stage_detail="Watchdog auto-restart")

        current_app.send_task(task_name, args=[order_id, config])
        logger.info(f"[Watchdog] Dispatched {task_name} for order {order_id}")

    except Exception as e:
        logger.error(f"[Watchdog] Failed to restart order {order_id}: {e}")


@current_app.task(name="watchdog.tasks.check_stalled_orders", bind=True, ignore_result=True)
def check_stalled_orders(self):
    """
    Periodic task: scan all active orders and detect stalled ones.
    Designed for Celery Beat with a 5-minute interval.
    """
    try:
        active_orders = _get_active_orders()
        if not active_orders:
            return

        celery_active_ids = _get_celery_active_order_ids()
        now_utc = datetime.now(timezone.utc)
        no_task_stall = get_int("WATCHDOG_NO_TASK_STALL_MINUTES", 15)
        no_progress_stall = get_int("WATCHDOG_NO_PROGRESS_STALL_MINUTES", 60)

        for order in active_orders:
            order_id = order["id"]

            if _is_in_cooldown(order["watchdog_alerted_at"]):
                continue

            has_celery_task = order_id in celery_active_ids
            latest_log = _get_latest_log_time(order_id)

            if latest_log:
                log_utc = latest_log.replace(tzinfo=timezone.utc) if latest_log.tzinfo is None else latest_log
                minutes_since_log = (now_utc - log_utc).total_seconds() / 60
            else:
                started = order.get("started_at")
                if started:
                    started_utc = started.replace(tzinfo=timezone.utc) if started.tzinfo is None else started
                    minutes_since_log = (now_utc - started_utc).total_seconds() / 60
                else:
                    minutes_since_log = 0

            if not has_celery_task and minutes_since_log >= no_task_stall:
                reason = (
                    f"No active Celery task found and no log activity for "
                    f"{int(minutes_since_log)} minutes"
                )
                _handle_stalled_order(order, reason)

            elif has_celery_task and minutes_since_log >= no_progress_stall:
                reason = (
                    f"Celery task is running but no progress updates for "
                    f"{int(minutes_since_log)} minutes (possible hang)"
                )
                _handle_stalled_order(order, reason)

        logger.info(
            f"[Watchdog] Check complete — {len(active_orders)} active orders, "
            f"{len(celery_active_ids)} Celery tasks"
        )

    except Exception as e:
        logger.error(f"[Watchdog] check_stalled_orders failed: {e}", exc_info=True)
