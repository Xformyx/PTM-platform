import json
import logging
import os
import threading

import redis

from common.db_update import get_order_status, insert_order_log, update_order_progress

logger = logging.getLogger("ptm-workers.progress")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CHANNEL_PREFIX = "order:progress:"

_redis_client = None
_redis_lock = threading.Lock()


def get_redis_client():
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                _redis_client = redis.from_url(
                    REDIS_URL, decode_responses=True,
                    socket_connect_timeout=5, socket_timeout=5,
                )
    return _redis_client


def publish_progress(
    order_id: int,
    stage: str,
    step: str,
    status: str,
    progress_pct: float,
    message: str = "",
    metadata: dict = None,
):
    if get_order_status(order_id) == "cancelled":
        return

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


def publish_analysis_log(
    order_id: int,
    message: str,
    *,
    stage: str = "rag_enrichment",
    step: str = "enrichment_detail",
    status: str = "progress",
    metadata: dict = None,
    persist: bool = False,
):
    """Publish a real-time event to Redis SSE.

    By default does NOT write to order_logs (DB) to avoid log bloat.
    Set persist=True for milestone events that should survive a page reload.
    """
    if get_order_status(order_id) == "cancelled":
        return

    if persist:
        insert_order_log(
            order_id=order_id,
            stage=stage,
            step=step,
            status=status,
            progress_pct=None,
            message=message,
            metadata=metadata,
        )
    try:
        r = get_redis_client()
        channel = f"{CHANNEL_PREFIX}{order_id}"
        payload = {
            "order_id": order_id,
            "stage": stage,
            "step": step,
            "status": status,
            "progress_pct": None,
            "message": message,
            "metadata": metadata or {},
        }
        r.publish(channel, json.dumps(payload))
    except Exception as e:
        logger.warning(f"Failed to publish analysis log: {e}")
