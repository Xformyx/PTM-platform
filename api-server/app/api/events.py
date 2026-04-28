import asyncio
import json
import logging

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.core.redis import get_redis
from app.dependencies import get_current_user

router = APIRouter(prefix="/events", tags=["events"])
logger = logging.getLogger("ptm-platform.events")

CHANNEL_PREFIX = "order:progress:"
PTMQUANT_CHANNEL_PREFIX = "ptmquant:progress:"


@router.get("/orders/{order_id}")
async def order_progress_stream(
    order_id: int,
    user=Depends(get_current_user),
):
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
    user=Depends(get_current_user),
):
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
