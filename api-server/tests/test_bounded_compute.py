"""Operational isolation for in-API CPU work. Does not change TMM scores."""

import asyncio

import pytest

from app.core import bounded_compute as bc
from app.core.bounded_compute import (
    CpuBoundBusy,
    CpuBoundTimeout,
    run_cpu_bound,
)


def test_run_cpu_bound_returns_fn_result():
    assert asyncio.run(run_cpu_bound(bc._test_add, 2, 3, timeout_sec=5)) == 5


def test_run_cpu_bound_kills_overtime_child():
    with pytest.raises(CpuBoundTimeout):
        asyncio.run(run_cpu_bound(bc._test_sleep, 8, timeout_sec=0.4))


def test_run_cpu_bound_rejects_overlapping_jobs():
    async def _overlap():
        first = asyncio.create_task(run_cpu_bound(bc._test_sleep, 1.2, timeout_sec=5))
        for _ in range(50):
            if bc._in_use:
                break
            await asyncio.sleep(0.02)
        assert bc._in_use
        with pytest.raises(CpuBoundBusy):
            await run_cpu_bound(bc._test_add, 1, 1, timeout_sec=5)
        assert await first == "done"

    asyncio.run(_overlap())
def test_cancelled_caller_does_not_release_running_child():
    async def scenario():
        import asyncio
        from app.core.bounded_compute import run_cpu_bound, CpuBoundBusy, _test_sleep
        caller = asyncio.create_task(run_cpu_bound(_test_sleep, .3, timeout_sec=5))
        await asyncio.sleep(.05)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        with pytest.raises(CpuBoundBusy):
            await run_cpu_bound(_test_sleep, .01, timeout_sec=5)
        from app.core import bounded_compute
        await asyncio.gather(*bounded_compute._running_tasks)
        assert await run_cpu_bound(_test_sleep, .01, timeout_sec=5) == "done"
    asyncio.run(scenario())
