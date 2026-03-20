"""Send order status events to webhook URLs (OpenClaw, etc.)."""
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("ptm-platform.webhook")

STEP_LABELS = {
    "preprocessing": "Preprocessing",
    "rag_enrichment": "RAG-enrichment",
    "report_generation": "Report Generation",
}
STATUS_LABELS = {
    "started": "Started",
    "completed": "Completed",
    "failed": "Failed",
    "cancelled": "Cancelled",
}


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

    step_label = STEP_LABELS.get(step, step)
    status_label = STATUS_LABELS.get(status, status)
    message = f"[{order_code}] {step_label} - {status_label}"

    payload = {
        "order_id": order_id,
        "order_code": order_code,
        "step": step,
        "status": status,
        "message": message,
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
