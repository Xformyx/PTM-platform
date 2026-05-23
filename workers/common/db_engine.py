"""
Shared SQLAlchemy sync engine singleton for all worker modules.

Every worker module that needs MySQL access should import `get_engine()`
from here instead of creating its own `create_engine` pool.
"""

import os
import threading

from sqlalchemy import create_engine

_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+asyncmy://ptm_user:ptm_password@localhost:3306/ptm_platform",
)
SYNC_DATABASE_URL = _DATABASE_URL.replace("+asyncmy", "+pymysql").replace("+aiomysql", "+pymysql")

_ENGINE = None
_ENGINE_LOCK = threading.Lock()


def get_engine():
    """Return the process-wide shared SQLAlchemy Engine (lazy-created, thread-safe)."""
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = create_engine(
                    SYNC_DATABASE_URL,
                    pool_pre_ping=True,
                    pool_size=5,
                    max_overflow=5,
                    pool_recycle=600,
                )
    return _ENGINE
