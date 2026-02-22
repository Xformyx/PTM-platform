import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.redis import get_redis

router = APIRouter(tags=["health"])
logger = logging.getLogger("ptm-platform.health")


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "ptm-api-server"}


@router.get("/health/detailed")
async def detailed_health(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    checks: dict[str, Any] = {}

    # MySQL
    try:
        await db.execute(text("SELECT 1"))
        checks["mysql"] = {"status": "ok"}
    except Exception as e:
        checks["mysql"] = {"status": "error", "detail": str(e)}

    # Redis
    try:
        r = await get_redis()
        await r.ping()
        checks["redis"] = {"status": "ok"}
    except Exception as e:
        checks["redis"] = {"status": "error", "detail": str(e)}

    # ChromaDB
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.CHROMADB_URL}/api/v2/heartbeat")
            if resp.status_code == 200:
                checks["chromadb"] = {"status": "ok"}
            else:
                checks["chromadb"] = {"status": "error", "code": resp.status_code}
    except Exception as e:
        checks["chromadb"] = {"status": "error", "detail": str(e)}

    # Ollama
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                checks["ollama"] = {
                    "status": "ok",
                    "models_count": len(models),
                }
            else:
                checks["ollama"] = {"status": "error", "code": resp.status_code}
    except Exception as e:
        checks["ollama"] = {"status": "unavailable", "detail": str(e)}

    overall = "ok" if all(
        c.get("status") == "ok" for name, c in checks.items() if name != "ollama"
    ) else "degraded"

    return {"status": overall, "checks": checks}
