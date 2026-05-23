"""
Read system settings from DB (system_settings table) with environment variable fallback.
Settings are cached briefly to avoid excessive DB queries.
"""
import logging
import os
import time
import threading

from sqlalchemy import text
from common.db_engine import get_engine as _get_engine

logger = logging.getLogger("ptm-workers.settings")

_cache: dict[str, str] = {}
_cache_ts: float = 0
_cache_lock = threading.Lock()
CACHE_TTL = 60  # seconds


def _refresh_cache():
    global _cache, _cache_ts
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT setting_key, setting_value FROM system_settings")
            ).fetchall()
        with _cache_lock:
            _cache = {r[0]: r[1] for r in rows}
            _cache_ts = time.time()
    except Exception as e:
        logger.debug(f"Failed to load system settings from DB: {e}")


def get_setting(key: str, default: str | None = None) -> str:
    """
    Get a setting value. Priority: DB > env > default.
    DB values are cached for CACHE_TTL seconds.
    """
    if time.time() - _cache_ts > CACHE_TTL:
        _refresh_cache()

    with _cache_lock:
        db_val = _cache.get(key)

    if db_val is not None:
        return db_val

    env_val = os.getenv(key)
    if env_val is not None:
        return env_val

    return default or ""


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(get_setting(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_bool(key: str, default: bool = False) -> bool:
    val = get_setting(key, str(default).lower())
    return val.lower() in ("1", "true", "yes")
