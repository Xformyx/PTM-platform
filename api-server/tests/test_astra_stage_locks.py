"""Cancel/restart clears only this Order's locks in their actual databases."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock


def test_preprocessing_broker_lock_is_cleared_separately(monkeypatch):
    from app.api import orders
    import redis.asyncio
    api=SimpleNamespace(delete=AsyncMock(return_value=1))
    broker=SimpleNamespace(delete=AsyncMock(return_value=1),aclose=AsyncMock())
    monkeypatch.setattr(orders,'get_redis',AsyncMock(return_value=api))
    monkeypatch.setattr(orders,'get_settings',lambda:SimpleNamespace(CELERY_BROKER_URL='redis://isolated/14'))
    def connect(url,**kwargs):
        assert url=='redis://isolated/14'
        return broker
    monkeypatch.setattr(redis.asyncio,'from_url',connect)
    assert asyncio.run(orders._clear_order_locks(73))==2
    api.delete.assert_awaited_once_with('report_gen_lock:73')
    broker.delete.assert_awaited_once_with('preprocessing_lock:73')
    broker.aclose.assert_awaited_once()
