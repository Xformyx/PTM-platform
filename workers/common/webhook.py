"""
Send pipeline step notifications to webhook URLs (Telegram agent, Slack, etc.).

JSON schema per request:
  - order_id:     int
  - order_code:   str
  - step:         "preprocessing" | "rag_enrichment" | "report_generation" | "order"
  - status:       "started" | "completed"
  - timestamp:    ISO 8601
  - project_name: str  (optional)
  - message:      str  (optional, human-readable)

Idempotency: (order_id, step, status) is recorded in `webhook_sent_log`.
             A duplicate combination is silently skipped.
Retry:       Exponential back-off, 3 attempts max.
"""

import json
import logging
import os
import time
import urllib.request
from datetime import datetime, timezone

from sqlalchemy import text

from common.db_engine import get_engine as _get_engine

logger = logging.getLogger("ptm-workers.webhook")

ALLOWED_STEPS = ("preprocessing", "rag_enrichment", "report_generation", "order")
ALLOWED_STATUSES = ("started", "completed")

_TABLE_READY = False


def _ensure_table():
    """Create webhook_sent_log if it does not exist (idempotency store)."""
    global _TABLE_READY
    if _TABLE_READY:
        return
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS webhook_sent_log (
                    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
                    order_id   INT          NOT NULL,
                    step       VARCHAR(32)  NOT NULL,
                    status     VARCHAR(16)  NOT NULL,
                    sent_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_order_step_status (order_id, step, status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.commit()
        _TABLE_READY = True
    except Exception as e:
        logger.warning(f"webhook_sent_log table creation failed (will retry next call): {e}")


def _already_sent(order_id: int, step: str, status: str) -> bool:
    """Return True if this (order_id, step, status) was already sent."""
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM webhook_sent_log WHERE order_id=:oid AND step=:step AND status=:status LIMIT 1"),
                {"oid": order_id, "step": step, "status": status},
            ).fetchone()
        return row is not None
    except Exception:
        return False


def _mark_sent(order_id: int, step: str, status: str):
    """Record that this webhook was delivered (INSERT IGNORE)."""
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("INSERT IGNORE INTO webhook_sent_log (order_id, step, status) VALUES (:oid, :step, :status)"),
                {"oid": order_id, "step": step, "status": status},
            )
            conn.commit()
    except Exception as e:
        logger.debug(f"webhook_sent_log mark failed: {e}")


def _get_order_info(order_id: int) -> dict:
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT order_code, project_name FROM orders WHERE id = :oid"),
                {"oid": order_id},
            ).fetchone()
        if row:
            return {"order_code": row[0] or "", "project_name": row[1] or ""}
    except Exception as e:
        logger.warning(f"[Order {order_id}] Webhook: failed to get order info: {e}")
    return {"order_code": "", "project_name": ""}


def _post_with_retry(url: str, payload: dict, max_attempts: int = 3) -> bool:
    """POST JSON with exponential back-off. Returns True on success."""
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(1, max_attempts + 1):
        try:
            req = urllib.request.Request(
                url, data=data, method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status < 400:
                    return True
                logger.warning(f"Webhook {url} returned {resp.status} (attempt {attempt})")
        except Exception as e:
            logger.warning(f"Webhook {url} attempt {attempt}/{max_attempts} failed: {e}")
        if attempt < max_attempts:
            time.sleep(2 ** attempt)
    return False


# ── Public API ────────────────────────────────────────────────────────────────

def send_step_webhook(
    order_id: int,
    step: str,
    status: str,
    message: str | None = None,
):
    """
    Send a pipeline step notification to all configured WEBHOOK_URLs.

    step:   preprocessing | rag_enrichment | report_generation | order
    status: started | completed
    """
    if step not in ALLOWED_STEPS or status not in ALLOWED_STATUSES:
        logger.debug(f"Webhook skipped: invalid step={step} status={status}")
        return

    urls_raw = os.getenv("WEBHOOK_URL", "").strip()
    if not urls_raw:
        return
    urls = [u.strip() for u in urls_raw.split(",") if u.strip()]
    if not urls:
        return

    _ensure_table()

    if _already_sent(order_id, step, status):
        logger.debug(f"[Order {order_id}] Webhook already sent: step={step} status={status}")
        return

    info = _get_order_info(order_id)

    step_labels = {
        "preprocessing": "Preprocessing",
        "rag_enrichment": "RAG Enrichment",
        "report_generation": "Report Generation",
        "order": "Pipeline",
    }
    status_labels = {"started": "Started", "completed": "Completed"}
    auto_message = f"[{info['order_code']}] {step_labels.get(step, step)} {status_labels.get(status, status)}"

    payload = {
        "order_id": order_id,
        "order_code": info["order_code"],
        "step": step,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project_name": info["project_name"],
        "message": message or auto_message,
    }

    ok = False
    for url in urls:
        if _post_with_retry(url, payload):
            ok = True

    if ok:
        _mark_sent(order_id, step, status)
        logger.info(f"[Order {order_id}] Webhook sent: step={step} status={status}")
    else:
        logger.warning(f"[Order {order_id}] Webhook delivery FAILED for step={step} status={status}")


