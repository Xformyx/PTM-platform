"""Run CPU-heavy callables off the API accept loop.

구현 대상: operational isolation after the 2026-09-18 login outage
사전등록: 해당 없음. 측정 공식·임계·solver를 바꾸지 않는다.
해석 한계: timeout은 요청 중단이다. 점수나 기여 비율을 재정의하지 않는다.
주장 금지: 이 격리로 kinase 귀속 정확도가 달라졌다고 쓰지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
from typing import Any, Callable

_log = logging.getLogger("ptm-platform.bounded_compute")

# One in-flight CPU job per API process.  A second heatmap TMM must not stack
# on the same core and starve login/health again.
_in_use = False
# Process-local admission only; production fleet admission belongs to its queue.
_running_tasks: set[asyncio.Task] = set()


class CpuBoundTimeout(TimeoutError):
    """Child process exceeded the operational wall-clock cap and was killed."""


class CpuBoundBusy(RuntimeError):
    """Another CPU-bound job is already running in this API process."""


def _bounded_worker(conn, fn: Callable[..., Any], args: tuple, kwargs: dict) -> None:
    try:
        conn.send(("ok", fn(*args, **kwargs)))
    except Exception as exc:  # noqa: BLE001 — child must always report
        conn.send(("err", f"{type(exc).__name__}: {exc}"))
    finally:
        conn.close()


def _run_in_process(
    fn: Callable[..., Any],
    args: tuple,
    kwargs: dict,
    timeout_sec: float,
) -> Any:
    """Spawn ``fn`` and kill it if it exceeds ``timeout_sec``.

    ``spawn`` is required: forking from a running uvicorn/asyncio process can
    deadlock.  Results are pickled back unchanged.
    """
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_bounded_worker,
        args=(child, fn, args, kwargs),
        daemon=True,
        name="ptm-api-cpu-bound",
    )
    proc.start()
    child.close()
    try:
        if parent.poll(timeout_sec):
            status, payload = parent.recv()
            proc.join(5)
            if status == "ok":
                return payload
            raise RuntimeError(payload)
        _log.warning(
            "CPU-bound job %s exceeded %.1fs — terminating child pid=%s",
            getattr(fn, "__name__", fn),
            timeout_sec,
            proc.pid,
        )
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join(5)
        raise CpuBoundTimeout(
            f"{getattr(fn, '__name__', 'cpu_bound')} exceeded {timeout_sec:.0f}s and was stopped"
        )
    finally:
        parent.close()
        if proc.is_alive():
            proc.kill()
            proc.join(5)


def _test_add(a, b):
    """Pickle-safe target for unit tests. Not a scoring function."""
    return a + b


def _test_sleep(seconds: float):
    """Pickle-safe target for unit tests. Not a scoring function."""
    import time

    time.sleep(float(seconds))
    return "done"


async def run_cpu_bound(
    fn: Callable[..., Any],
    /,
    *args: Any,
    timeout_sec: float,
    **kwargs: Any,
) -> Any:
    """Await ``fn`` in a child process; keep the uvicorn event loop free.

    Same return value as ``fn(*args, **kwargs)`` when it finishes in time.
    """
    global _in_use
    if _in_use:
        raise CpuBoundBusy(
            "A CPU-bound kinase computation is already running on this API process"
        )
    _in_use = True
    task = asyncio.create_task(asyncio.to_thread(_run_in_process, fn, args, kwargs, float(timeout_sec)))
    _running_tasks.add(task)
    def release(completed):
        global _in_use
        _running_tasks.discard(completed)
        _in_use = False
        # Consume an exception even if the HTTP caller disconnected.
        if not completed.cancelled():
            completed.exception()
    task.add_done_callback(release)
    # Await cancellation does not stop a thread or its child. Keep the slot until
    # _run_in_process has actually joined/terminated that child.
    return await asyncio.shield(task)
