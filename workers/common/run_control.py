"""Per-order run generation and Celery task-id tracking.

구현 대상: 실행 게이트 (측정 상수 아님). cancel 후 재시작 시 이전 워커가
산출 파일을 덮어쓰지 않게 한다.
사전등록: 해당 없음.
해석 한계: 워커 프로세스의 즉시 SIGKILL을 보장하지 않는다. 상태/파일 쓰기만 막는다.
주장 금지: 이 값으로 분석 정확도를 논하지 않는다.

Redis keys are shared with api-server/app/api/orders.py:
  celery_task:{id}      latest task id
  celery_tasks:{id}     SET of task ids for this run
  order_run_gen:{id}    integer generation, incremented on each start/run-stage
"""

from __future__ import annotations

import logging
import os
import threading

import redis

logger = logging.getLogger("ptm-workers.run-control")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_CELERY_TASK_KEY = "celery_task:{order_id}"
_CELERY_TASKS_SET = "celery_tasks:{order_id}"
_RUN_GEN_KEY = "order_run_gen:{order_id}"
_TTL = 7 * 24 * 3600

_tls = threading.local()
_redis_client = None
_redis_lock = threading.Lock()


class RunSuperseded(Exception):
    """This worker belongs to a cancelled or replaced pipeline run."""


def _redis():
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                _redis_client = redis.from_url(
                    REDIS_URL, decode_responses=True,
                    socket_connect_timeout=5, socket_timeout=5,
                )
    return _redis_client


def save_celery_task_id(order_id: int, task_id: str) -> None:
    """Record a Celery task id (latest + set) so cancel can revoke the chain."""
    if not task_id:
        return
    try:
        r = _redis()
        pipe = r.pipeline()
        pipe.set(_CELERY_TASK_KEY.format(order_id=order_id), task_id, ex=_TTL)
        pipe.sadd(_CELERY_TASKS_SET.format(order_id=order_id), task_id)
        pipe.expire(_CELERY_TASKS_SET.format(order_id=order_id), _TTL)
        pipe.execute()
    except Exception as exc:
        logger.warning(f"Failed to persist celery task id for order {order_id}: {exc}")


def get_run_generation(order_id: int) -> int | None:
    try:
        val = _redis().get(_RUN_GEN_KEY.format(order_id=order_id))
        if val is None:
            return None
        return int(val)
    except Exception:
        return None


def is_stale_generation(order_id: int, expected: int | None) -> bool:
    """True if a newer start/run-stage has claimed this order.

    Missing Redis key → not stale (first run / Redis blip).
    expected is None but Redis has a generation → this task predates the claim.
    """
    current = get_run_generation(order_id)
    if current is None:
        return False
    if expected is None:
        return True
    return int(current) != int(expected)


def bind_run_generation(order_id: int, generation: int | None) -> None:
    _tls.order_id = order_id
    _tls.generation = generation


def bound_run_is_stale() -> bool:
    gen = getattr(_tls, "generation", None)
    oid = getattr(_tls, "order_id", None)
    if oid is None:
        return False
    return is_stale_generation(int(oid), gen)


def abort_if_superseded(order_id: int) -> None:
    """Raise RunSuperseded if the order was cancelled or this run was replaced."""
    from common.db_update import get_order_status

    if get_order_status(order_id) == "cancelled" or bound_run_is_stale():
        raise RunSuperseded(f"order {order_id} run superseded")
