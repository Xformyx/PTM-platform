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

# Events: only 3 — Started, Completed, Failed/Cancelled
EVENTS = ("started", "completed", "failed", "cancelled")


_ENGINE = None
_ENGINE_LOCK = __import__("threading").Lock()


def _get_engine():
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = create_engine(
                    SYNC_DATABASE_URL,
                    pool_pre_ping=True,
                    pool_size=1,
                    max_overflow=2,
                    pool_recycle=600,
                )
    return _ENGINE


def _get_order_info(order_id: int) -> dict:
    """Fetch order_code, project_name for webhook payload."""
    try:
        engine = _get_engine()
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
    event: str,
    error_message: str | None = None,
):
    """
    Send order event to configured webhook URL(s).
    event: started | completed | failed | cancelled

    Only 3 moments: analysis started, analysis completed, error/stop.
    Message format: [order_code] Started | Completed | Failed | Cancelled
    """
    if event not in EVENTS:
        return

    urls = os.getenv("WEBHOOK_URL", "").strip()
    if not urls:
        return

    urls = [u.strip() for u in urls.split(",") if u.strip()]
    if not urls:
        return

    info = _get_order_info(order_id)
    labels = {"started": "Started", "completed": "Completed", "failed": "Failed", "cancelled": "Cancelled"}
    message = f"[{info['order_code']}] {labels.get(event, event)}"

    payload = {
        "order_id": order_id,
        "order_code": info["order_code"],
        "event": event,
        "status": event,
        "message": message,
        "error_message": error_message or info["error_message"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    for url in urls:
        _send_one(url, payload)
