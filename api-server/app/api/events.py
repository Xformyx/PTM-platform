import asyncio
import json
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.orders import _check_order_access_async
from app.api.ptmquant import can_access_ptmquant_job
from app.core.database import get_db
from app.core.redis import get_redis
from app.dependencies import get_current_user, get_sse_user
from app.models.order import Order
from app.models.ptmquant_job import PTMQuantJob

router = APIRouter(prefix="/events", tags=["events"])
logger = logging.getLogger("ptm-platform.events")

CHANNEL_PREFIX = "order:progress:"
PTMQUANT_CHANNEL_PREFIX = "ptmquant:progress:"
_SSE_TICKET_TTL = 120


@router.post("/ticket")
async def issue_sse_ticket(user=Depends(get_current_user)):
    """Issue a short-lived ticket so EventSource URLs do not carry the JWT."""
    ticket = secrets.token_urlsafe(32)
    redis = await get_redis()
    await redis.set(f"sse_ticket:{ticket}", str(getattr(user, "id", 0)), ex=_SSE_TICKET_TTL)
    return {"ticket": ticket, "expires_in": _SSE_TICKET_TTL}


@router.get("/orders/{order_id}")
async def order_progress_stream(
    order_id: int,
    user=Depends(get_sse_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    await _check_order_access_async(order, user, db)

    async def event_generator():
        redis = await get_redis()
        pubsub = redis.pubsub()
        channel = f"{CHANNEL_PREFIX}{order_id}"
        await pubsub.subscribe(channel)

        try:
            idle_cycles = 0
            while True:
                batch: list[str] = []
                for _ in range(50):
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=0.05
                    )
                    if message and message["type"] == "message":
                        batch.append(message["data"])
                    else:
                        break

                if batch:
                    for data in batch:
                        yield {"event": "progress", "data": data}
                    idle_cycles = 0
                else:
                    idle_cycles += 1
                    if idle_cycles % 10 == 0:
                        yield {"event": "ping", "data": ""}

                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    return EventSourceResponse(event_generator())


@router.get("/ptmquant/{job_id}")
async def ptmquant_progress_stream(
    job_id: str,
    user=Depends(get_sse_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PTMQuantJob).where(PTMQuantJob.job_id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not can_access_ptmquant_job(job, user):
        raise HTTPException(status_code=403, detail="Not authorized to access this job")

    async def event_generator():
        redis = await get_redis()
        pubsub = redis.pubsub()
        channel = f"{PTMQUANT_CHANNEL_PREFIX}{job_id}"
        await pubsub.subscribe(channel)

        try:
            idle_cycles = 0
            while True:
                batch: list[str] = []
                for _ in range(50):
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=0.05
                    )
                    if message and message["type"] == "message":
                        batch.append(message["data"])
                    else:
                        break

                if batch:
                    for data in batch:
                        yield {"event": "progress", "data": data}
                    idle_cycles = 0

                    # Auto-close if job finished
                    try:
                        last = json.loads(batch[-1])
                        if last.get("type") in ("done", "error"):
                            return
                    except Exception:
                        pass
                else:
                    idle_cycles += 1
                    if idle_cycles % 10 == 0:
                        yield {"event": "ping", "data": ""}

                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    return EventSourceResponse(event_generator())
