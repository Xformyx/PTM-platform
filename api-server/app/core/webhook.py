"""Send order events to webhook URLs (OpenClaw, etc.).
Only 3 moments: Started, Completed, Failed/Cancelled.
"""
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("ptm-platform.webhook")

EVENTS = ("started", "completed", "failed", "cancelled")
LABELS = {"started": "Started", "completed": "Completed", "failed": "Failed", "cancelled": "Cancelled"}


async def send_order_webhook(
    order_id: int,
    order_code: str,
    event: str,
    error_message: str | None = None,
    webhook_url: str | None = None,
):
    """POST order event to webhook URL(s). event: started | completed | failed | cancelled"""
    url = webhook_url or ""
    if not url.strip():
        return

    urls = [u.strip() for u in url.split(",") if u.strip()]
    if not urls:
        return

    if event not in EVENTS:
        return

    message = f"[{order_code}] {LABELS.get(event, event)}"

    payload = {
        "order_id": order_id,
        "order_code": order_code,
        "event": event,
        "status": event,
        "message": message,
        "error_message": error_message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        for u in urls:
            try:
                resp = await client.post(u, json=payload)
                if resp.status_code >= 400:
                    logger.warning(f"Webhook {u} returned {resp.status_code}: {resp.text[:200]}")
                else:
                    logger.info(f"Webhook OK: {u} -> {resp.status_code}")
            except Exception as e:
                logger.warning(f"Webhook failed for {u}: {e}")
