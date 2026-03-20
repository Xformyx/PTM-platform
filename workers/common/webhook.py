"""
Send order status events to webhook URLs (OpenClaw, Slack, etc.).
Supports multiple URLs (comma-separated in WEBHOOK_URL).
"""
import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

logger = logging.getLogger("ptm-workers.webhook")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+asyncmy://ptm_user:ptm_password@localhost:3306/ptm_platform",
)
SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncmy", "+pymysql").replace("+aiomysql", "+pymysql")

# step: 3 stages. status: result (started/completed/failed/cancelled)
STEPS = ("preprocessing", "rag_enrichment", "report_generation")
STATUSES = ("started", "completed", "failed", "cancelled")


def _get_order_info(order_id: int) -> dict:
    """Fetch order_code, project_name for webhook payload."""
    try:
        engine = create_engine(SYNC_DATABASE_URL, pool_pre_ping=True, pool_size=1)
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT order_code, project_name, status, current_stage, error_message FROM orders WHERE id = :order_id"),
                {"order_id": order_id},
            ).fetchone()
        if row:
            return {
                "order_code": row[0] or "",
                "project_name": row[1] or "",
                "status": row[2] or "",
                "current_stage": row[3] or "",
                "error_message": row[4] or None,
            }
    except Exception as e:
        logger.warning(f"[Order {order_id}] Webhook: failed to get order info: {e}")
    return {"order_code": "", "project_name": "", "status": "", "current_stage": "", "error_message": None}


def _send_one(url: str, payload: dict) -> bool:
    """POST payload to a single URL. Returns True on success."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 400:
                logger.warning(f"Webhook {url} returned {resp.status}")
                return False
        return True
    except Exception as e:
        logger.warning(f"Webhook failed for {url}: {e}")
        return False


def send_order_webhook(
    order_id: int,
    step: str | None,
    status: str,
    error_message: str | None = None,
):
    """
    Send order stage event to configured webhook URL(s).
    step: preprocessing | rag_enrichment | report_generation (None = use current_stage from DB)
    status: started | completed | failed | cancelled

    Format for OpenClaw: [order_code] Step : Status
    """
    if status not in STATUSES:
        return

    urls = os.getenv("WEBHOOK_URL", "").strip()
    if not urls:
        return

    urls = [u.strip() for u in urls.split(",") if u.strip()]
    if not urls:
        return

    info = _get_order_info(order_id)
    if step is None:
        step = info["current_stage"] if info["current_stage"] in STEPS else "preprocessing"
    if step not in STEPS:
        return

    payload = {
        "order_id": order_id,
        "order_code": info["order_code"],
        "step": step,
        "status": status,
        "error_message": error_message or info["error_message"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    for url in urls:
        _send_one(url, payload)
