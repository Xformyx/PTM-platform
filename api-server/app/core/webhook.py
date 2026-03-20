"""Send order status events to webhook URLs (OpenClaw, etc.)."""
import asyncio
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("ptm-platform.webhook")


async def send_order_webhook(
    order_id: int,
    order_code: str,
    step: str,
    status: str,
    error_message: str | None = None,
    webhook_url: str | None = None,
):
    """POST order event to webhook URL(s). Comma-separated URLs supported."""
    url = webhook_url or ""
    if not url.strip():
        return

    urls = [u.strip() for u in url.split(",") if u.strip()]
    if not urls:
        return

    payload = {
        "order_id": order_id,
        "order_code": order_code,
        "step": step,
        "status": status,
        "error_message": error_message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        for u in urls:
            try:
                resp = await client.post(u, json=payload)
                if resp.status_code >= 400:
                    logger.warning(f"Webhook {u} returned {resp.status_code}")
            except Exception as e:
                logger.warning(f"Webhook failed for {u}: {e}")
