import json
import logging
import os

import redis

from common.db_update import insert_order_log, update_order_progress

logger = logging.getLogger("ptm-workers.progress")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CHANNEL_PREFIX = "order:progress:"


def get_redis_client():
    return redis.from_url(REDIS_URL, decode_responses=True)


def publish_progress(
    order_id: int,
    stage: str,
    step: str,
    status: str,
    progress_pct: float,
    message: str = "",
    metadata: dict = None,
):
    payload = {
        "order_id": order_id,
        "stage": stage,
        "step": step,
        "status": status,
        "progress_pct": progress_pct,
        "message": message,
        "metadata": metadata or {},
    }

    # Update orders.progress_pct, stage_detail, and current_stage in DB
    if progress_pct >= 0:
        update_order_progress(order_id, progress_pct, message, current_stage=stage)

    # Persist to order_logs table
    insert_order_log(
        order_id=order_id,
        stage=stage,
        step=step,
        status=status,
        progress_pct=progress_pct if progress_pct >= 0 else None,
        message=message,
        metadata=metadata,
    )

    # Publish to Redis for real-time SSE
    try:
        r = get_redis_client()
        channel = f"{CHANNEL_PREFIX}{order_id}"
        r.publish(channel, json.dumps(payload))
        logger.debug(f"Progress published: order={order_id} stage={stage} step={step} {progress_pct}%")
    except Exception as e:
        logger.warning(f"Failed to publish progress: {e}")
