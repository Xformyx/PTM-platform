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


@router.get("/health/system-architecture")
async def system_architecture(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """
    Returns system architecture with connectivity status for each node.
    Used by System Monitor page for visual diagram.
    """
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    # API Server (self) - always ok if we reach this
    nodes["api_server"] = {
        "id": "api_server",
        "label": "API Server",
        "host": "api-server",
        "port": 8000,
        "status": "ok",
        "detail": "Running",
    }

    # Gateway - inferred: if this endpoint returns, gateway is working
    nodes["gateway"] = {
        "id": "gateway",
        "label": "Gateway (nginx)",
        "host": "gateway",
        "port": 80,
        "status": "ok",
        "detail": "Request reached API",
    }

    # MySQL
    try:
        await db.execute(text("SELECT 1"))
        nodes["mysql"] = {
            "id": "mysql",
            "label": "MySQL",
            "host": "mysql",
            "port": 3306,
            "status": "ok",
            "detail": "Connected",
        }
    except Exception as e:
        nodes["mysql"] = {
            "id": "mysql",
            "label": "MySQL",
            "host": "mysql",
            "port": 3306,
            "status": "error",
            "detail": str(e)[:80],
        }

    # Redis
    try:
        r = await get_redis()
        await r.ping()
        nodes["redis"] = {
            "id": "redis",
            "label": "Redis",
            "host": "redis",
            "port": 6379,
            "status": "ok",
            "detail": "Connected",
        }
    except Exception as e:
        nodes["redis"] = {
            "id": "redis",
            "label": "Redis",
            "host": "redis",
            "port": 6379,
            "status": "error",
            "detail": str(e)[:80],
        }

    # ChromaDB
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.CHROMADB_URL}/api/v2/heartbeat")
            if resp.status_code == 200:
                nodes["chromadb"] = {
                    "id": "chromadb",
                    "label": "ChromaDB",
                    "host": "chromadb",
                    "port": 8000,
                    "status": "ok",
                    "detail": "Connected",
                }
            else:
                nodes["chromadb"] = {
                    "id": "chromadb",
                    "label": "ChromaDB",
                    "host": "chromadb",
                    "port": 8000,
                    "status": "error",
                    "detail": f"HTTP {resp.status_code}",
                }
    except Exception as e:
        nodes["chromadb"] = {
            "id": "chromadb",
            "label": "ChromaDB",
            "host": "chromadb",
            "port": 8000,
            "status": "error",
            "detail": str(e)[:80],
        }

    # MCP Server
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            base = (settings.MCP_SERVER_URL or "").rstrip("/")
            url = f"{base}/health" if base else "http://localhost:8001/health"
            resp = await client.get(url)
            if resp.status_code == 200:
                nodes["mcp_server"] = {
                    "id": "mcp_server",
                    "label": "MCP Server",
                    "host": "mcp-server",
                    "port": 8001,
                    "status": "ok",
                    "detail": "Connected",
                }
            else:
                nodes["mcp_server"] = {
                    "id": "mcp_server",
                    "label": "MCP Server",
                    "host": "mcp-server",
                    "port": 8001,
                    "status": "error",
                    "detail": f"HTTP {resp.status_code}",
                }
    except Exception as e:
        nodes["mcp_server"] = {
            "id": "mcp_server",
            "label": "MCP Server",
            "host": "mcp-server",
            "port": 8001,
            "status": "error",
            "detail": str(e)[:80],
        }

    # Ollama
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                nodes["ollama"] = {
                    "id": "ollama",
                    "label": "Ollama",
                    "host": "host",
                    "port": 11434,
                    "status": "ok",
                    "detail": f"{len(models)} models",
                }
            else:
                nodes["ollama"] = {
                    "id": "ollama",
                    "label": "Ollama",
                    "host": "host",
                    "port": 11434,
                    "status": "error",
                    "detail": f"HTTP {resp.status_code}",
                }
    except Exception as e:
        nodes["ollama"] = {
            "id": "ollama",
            "label": "Ollama",
            "host": "host",
            "port": 11434,
            "status": "unavailable",
            "detail": str(e)[:80],
        }

    # Edges (connections)
    edges = [
        {"from": "client", "to": "gateway", "label": "HTTPS", "status": "ok"},
        {"from": "gateway", "to": "api_server", "label": "8000", "status": "ok"},
        {"from": "api_server", "to": "mysql", "label": "3306", "status": nodes.get("mysql", {}).get("status", "unknown")},
        {"from": "api_server", "to": "redis", "label": "6379", "status": nodes.get("redis", {}).get("status", "unknown")},
        {"from": "api_server", "to": "chromadb", "label": "8000", "status": nodes.get("chromadb", {}).get("status", "unknown")},
        {"from": "api_server", "to": "mcp_server", "label": "8001", "status": nodes.get("mcp_server", {}).get("status", "unknown")},
        {"from": "api_server", "to": "ollama", "label": "11434", "status": nodes.get("ollama", {}).get("status", "unknown")},
    ]

    # Client node (frontend)
    nodes["client"] = {
        "id": "client",
        "label": "Client",
        "host": "-",
        "port": 0,
        "status": "ok",
        "detail": "Browser",
    }

    return {"nodes": nodes, "edges": edges}
