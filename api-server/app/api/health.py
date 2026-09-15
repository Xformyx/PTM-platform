import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.git_date import format_git_date_kst
from app.core.redis import get_redis
from app.core.runtime_banner import (
    LAST_DEPLOY_PATH,
    format_kst,
    load_last_deploy,
    parse_docker_ts,
    pick_applied_at,
    short_label,
    summarize_runtime,
)
from app.dependencies import get_current_user, require_role, require_sse_role

router = APIRouter(tags=["health"])
logger = logging.getLogger("ptm-platform.health")


def _resolve_ptm_agent_health_url(settings: Settings) -> str:
    explicit = (settings.PTM_AGENT_HEALTH_URL or "").strip().rstrip("/")
    if explicit:
        return explicit
    webhook = (settings.WEBHOOK_URL or "").strip()
    if webhook:
        parsed = urlparse(webhook)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}/health"
    return "http://host.docker.internal:9100/health"


def classify_ptm_agent_payload(data: Any) -> tuple[str, list[str]]:
    """Map openclaw-home /health JSON to ok|error. Does not probe the network."""
    if not isinstance(data, dict):
        return "error", ["invalid health body"]
    detail_parts: list[str] = []
    if data.get("uptime_seconds") is not None:
        detail_parts.append(f"uptime {data['uptime_seconds']}s")
    if data.get("pid"):
        detail_parts.append(f"pid {data['pid']}")
    polling = data.get("telegram_polling")
    if polling is True:
        detail_parts.append("polling")
    status = "ok" if data.get("status") == "ok" else "error"
    if status == "ok" and polling is False:
        status = "error"
        detail_parts.append("telegram polling off")
    return status, detail_parts


async def _check_ptm_agent(settings: Settings) -> dict[str, Any]:
    url = _resolve_ptm_agent_health_url(settings)
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return {
                    "status": "error",
                    "detail": f"HTTP {resp.status_code}",
                    "url": url,
                    "telegram_polling": None,
                }
            data = resp.json()
            status, detail_parts = classify_ptm_agent_payload(data)
            return {
                "status": status,
                "detail": ", ".join(detail_parts) or "Telegram agent",
                "url": url,
                "service": data.get("service") if isinstance(data, dict) else None,
                "started_at": data.get("started_at") if isinstance(data, dict) else None,
                "uptime_seconds": data.get("uptime_seconds") if isinstance(data, dict) else None,
                "pid": data.get("pid") if isinstance(data, dict) else None,
                "telegram_polling": data.get("telegram_polling") if isinstance(data, dict) else None,
            }
    except Exception as e:
        return {
            "status": "unavailable",
            "detail": str(e)[:120],
            "url": url,
            "telegram_polling": None,
        }


@router.get("/health/ptm-agent")
async def ptm_agent_health(
    settings: Settings = Depends(get_settings),
    _user=Depends(require_role("admin")),
) -> dict[str, Any]:
    """Sidebar / System Monitor probe for the host Telegram agent."""
    return await _check_ptm_agent(settings)


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "ptm-api-server"}


def _read_version_files() -> dict[str, str]:
    v = "0.0.0"
    git_hash = ""
    git_date = ""
    try:
        with open("/app/VERSION", "r") as f:
            v = f.read().strip() or "0.0.0"
    except FileNotFoundError:
        pass
    try:
        with open("/app/GIT_HASH", "r") as f:
            git_hash = f.read().strip() or ""
    except FileNotFoundError:
        pass
    try:
        with open("/app/GIT_DATE", "r") as f:
            git_date = f.read().strip() or ""
    except FileNotFoundError:
        pass
    file_date = format_git_date_kst(git_date)
    # Sidebar used to show this as "now". Prefer the last deploy event so a
    # morning restart is not stuck on the overnight commit clock.
    applied = pick_applied_at(load_last_deploy(LAST_DEPLOY_PATH), None, file_date)
    return {"version": v, "git_hash": git_hash, "git_date": applied or file_date}


@router.get("/version")
async def get_version() -> dict[str, str]:
    """Return platform SemVer (Major.Minor.Patch), git hash, and commit date."""
    return _read_version_files()


@router.get("/health/detailed")
async def detailed_health(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _user=Depends(get_current_user),
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

    checks["ptm_agent"] = await _check_ptm_agent(settings)

    overall = "ok" if all(
        c.get("status") == "ok"
        for name, c in checks.items()
        if name not in ("ollama", "ptm_agent")
    ) else "degraded"

    return {"status": overall, "checks": checks}


@router.get("/health/cloud-llm")
async def cloud_llm_health(
    settings: Settings = Depends(get_settings),
    _current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """
    Test Cloud LLM API connectivity (Gemini, OpenAI).
    Uses API keys from .env. No auth required for quick pre-flight check.
    """
    import os

    result: dict[str, Any] = {"gemini": None, "openai": None}

    # Gemini
    gemini_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    if gemini_key:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {gemini_key}",
                    },
                    json={
                        "model": gemini_model,
                        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                        "max_tokens": 10,
                    },
                )
                if resp.status_code == 200:
                    preview = (resp.json().get("choices", [{}])[0].get("message", {}).get("content", "") or "")[:50]
                    result["gemini"] = {"status": "ok", "model": gemini_model, "response_preview": preview.strip()}
                else:
                    result["gemini"] = {"status": "error", "code": resp.status_code, "detail": resp.text[:200]}
        except Exception as e:
            result["gemini"] = {"status": "error", "detail": str(e)}
    else:
        result["gemini"] = {"status": "skipped", "detail": "GEMINI_API_KEY not set"}

    # OpenAI (optional)
    openai_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    if openai_key:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {openai_key}",
                    },
                    json={
                        "model": openai_model,
                        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                        "max_tokens": 10,
                    },
                )
                if resp.status_code == 200:
                    preview = (resp.json().get("choices", [{}])[0].get("message", {}).get("content", "") or "")[:50]
                    result["openai"] = {"status": "ok", "model": openai_model, "response_preview": preview.strip()}
                else:
                    result["openai"] = {"status": "error", "code": resp.status_code, "detail": resp.text[:200]}
        except Exception as e:
            result["openai"] = {"status": "error", "detail": str(e)}
    else:
        result["openai"] = {"status": "skipped", "detail": "OPENAI_API_KEY not set"}

    return result


@router.get("/health/system-architecture")
async def system_architecture(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _user=Depends(require_role("admin")),
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

    # Cytoscape (Report network visualization — host.docker.internal)
    cytoscape_url = f"http://{settings.CYTOSCAPE_HOST}:{settings.CYTOSCAPE_PORT}/v1"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(cytoscape_url)
            if resp.status_code == 200:
                nodes["cytoscape"] = {
                    "id": "cytoscape",
                    "label": "Cytoscape",
                    "host": settings.CYTOSCAPE_HOST,
                    "port": settings.CYTOSCAPE_PORT,
                    "status": "ok",
                    "detail": "Report network viz",
                }
            else:
                nodes["cytoscape"] = {
                    "id": "cytoscape",
                    "label": "Cytoscape",
                    "host": settings.CYTOSCAPE_HOST,
                    "port": settings.CYTOSCAPE_PORT,
                    "status": "error",
                    "detail": f"HTTP {resp.status_code}",
                }
    except Exception as e:
        nodes["cytoscape"] = {
            "id": "cytoscape",
            "label": "Cytoscape",
            "host": settings.CYTOSCAPE_HOST,
            "port": settings.CYTOSCAPE_PORT,
            "status": "unavailable",
            "detail": str(e)[:80],
        }

    agent_check = await _check_ptm_agent(settings)
    agent_url = agent_check.get("url") or _resolve_ptm_agent_health_url(settings)
    agent_parsed = urlparse(agent_url)
    agent_host = agent_parsed.hostname or "host.docker.internal"
    agent_port = agent_parsed.port or 9100
    nodes["ptm_agent"] = {
        "id": "ptm_agent",
        "label": "PTM Agent (Telegram)",
        "host": agent_host,
        "port": agent_port,
        "status": agent_check.get("status", "unavailable"),
        "detail": agent_check.get("detail", ""),
        "telegram_polling": agent_check.get("telegram_polling"),
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
        {"from": "api_server", "to": "cytoscape", "label": "1234", "status": nodes.get("cytoscape", {}).get("status", "unknown")},
        {"from": "api_server", "to": "ptm_agent", "label": "webhook", "status": nodes.get("ptm_agent", {}).get("status", "unknown")},
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


# Docker log timestamp pattern (UTC): 2026-03-12T05:02:47.968Z or 2026-03-12 05:02:47.968
_DOCKER_TS_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)Z?\s*"
)
# Python logging format: [2026-03-12 09:30:27,976: INFO/ForkPoolWorker-2] — strip to avoid duplicate
_PYTHON_LOG_TS_PATTERN = re.compile(
    r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+: (INFO|DEBUG|WARNING|ERROR|CRITICAL)([^\]]*)\]\s*"
)


def _convert_log_timestamps_to_kst(logs: str) -> str:
    """Convert Docker's leading UTC timestamps to KST; remove duplicate Python timestamps."""
    kst = ZoneInfo("Asia/Seoul")
    lines = logs.split("\n")
    result = []
    for line in lines:
        m = _DOCKER_TS_PATTERN.match(line)
        if m:
            ts_str = m.group(1).replace("T", " ")
            try:
                dt = datetime.fromisoformat(ts_str.replace(" ", "T"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo("UTC"))
                dt_kst = dt.astimezone(kst)
                kst_str = dt_kst.strftime("%Y-%m-%d %H:%M:%S")
                rest = line[m.end() :].lstrip()
                # Strip Python logging timestamp to avoid duplication
                pm = _PYTHON_LOG_TS_PATTERN.match(rest)
                if pm:
                    rest = f"{pm.group(1)}{pm.group(2)} {rest[pm.end():].lstrip()}".rstrip()
                result.append(f"{kst_str} {rest}" if rest else kst_str)
            except (ValueError, TypeError):
                result.append(line)
        else:
            result.append(line)
    return "\n".join(result)


# Container list for log viewer (PTM containers from docker-compose)
CONTAINER_OPTIONS = [
    {"id": "ptm-worker-preprocessing", "label": "Preprocessing Worker", "category": "pipeline"},
    {"id": "ptm-worker-rag", "label": "RAG Enrichment Worker", "category": "pipeline"},
    {"id": "ptm-worker-report", "label": "Report Generation Worker", "category": "pipeline"},
    {"id": "ptm-celery-beat", "label": "Celery Beat (Watchdog)", "category": "pipeline"},
    {"id": "ptm-api-server", "label": "API Server", "category": "app"},
    {"id": "ptm-mcp-server", "label": "MCP Server", "category": "app"},
    {"id": "ptm-gateway", "label": "Gateway (nginx)", "category": "app"},
    {"id": "ptm-frontend", "label": "Frontend (UI)", "category": "app"},
    {"id": "ptm-mysql", "label": "MySQL", "category": "infra"},
    {"id": "ptm-redis", "label": "Redis", "category": "infra"},
    {"id": "ptm-chromadb", "label": "ChromaDB", "category": "infra"},
]


@router.get("/health/containers")
async def list_containers(_user=Depends(require_role("admin"))) -> dict:
    """List PTM containers available for log viewing."""
    return {"containers": CONTAINER_OPTIONS}


def _find_container(client, expected_id: str):
    """Find container by id/name. Handles Docker Compose project prefix and name variants."""
    try:
        return client.containers.get(expected_id)
    except Exception:
        pass
    # Fallback: list all and match by name (handles project prefix, e.g. ptm-platform_ptm-api-server)
    for c in client.containers.list(all=True):
        name = (c.name or "").lstrip("/")
        if name == expected_id or name.endswith(f"-{expected_id}") or name.endswith(f"_{expected_id}") or expected_id in name:
            return c
    return None


def _unavailable_container(opt: dict, detail: str) -> dict:
    return {
        "id": opt["id"],
        "label": opt["label"],
        "short": short_label(opt["id"]),
        "category": opt["category"],
        "status": "unavailable",
        "detail": detail[:80],
        "image": "",
        "image_id": "",
        "image_created": "",
        "image_created_kst": "",
        "started_at": "",
        "started_at_kst": "",
    }


def _inspect_container(container, opt: dict) -> dict:
    status = container.status
    attrs = container.attrs or {}
    image_name = ""
    image_id = ""
    image_created = ""
    try:
        image_obj = getattr(container, "image", None)
        if image_obj is not None:
            tags = getattr(image_obj, "tags", None) or []
            if tags:
                image_name = tags[0]
            raw_id = getattr(image_obj, "id", "") or ""
            image_id = raw_id.replace("sha256:", "")[:12]
            image_created = (getattr(image_obj, "attrs", None) or {}).get("Created", "") or ""
    except Exception:
        pass
    if not image_name:
        image_name = attrs.get("Config", {}).get("Image", "") or ""
    started_at = (attrs.get("State", {}) or {}).get("StartedAt") or ""
    return {
        "id": opt["id"],
        "label": opt["label"],
        "short": short_label(opt["id"]),
        "category": opt["category"],
        "status": "ok" if status == "running" else "error",
        "detail": status,
        "image": image_name,
        "image_id": image_id,
        "image_created": image_created,
        "image_created_kst": format_kst(parse_docker_ts(image_created)),
        "started_at": started_at,
        "started_at_kst": format_kst(parse_docker_ts(started_at)),
    }


def _collect_container_status() -> list[dict]:
    result = []
    try:
        import docker
        client = docker.from_env()
        for opt in CONTAINER_OPTIONS:
            try:
                container = _find_container(client, opt["id"])
                if container is None:
                    raise Exception(f"Container {opt['id']} not found")
                result.append(_inspect_container(container, opt))
            except Exception as e:
                result.append(_unavailable_container(opt, str(e)))
    except Exception as e:
        logger.warning(f"Container status failed: {e}")
        for opt in CONTAINER_OPTIONS:
            result.append(_unavailable_container(opt, str(e)))
    return result


@router.get("/health/container-status")
async def container_status(_user=Depends(require_role("admin"))) -> dict:
    """Return status of all PTM containers (running, exited, etc.)."""
    return {"containers": _collect_container_status()}


@router.get("/health/runtime-banner")
async def runtime_banner(_user=Depends(require_role("admin"))) -> dict:
    """Sidebar footer: baked version plus live restart/image times.

    ``applied_at_kst`` is the newest live stamp (deploy event or container
    start). ``git_date`` is only the bind-mounted GIT_DATE file.
    """
    version = _read_version_files()
    containers = _collect_container_status()
    last_deploy = load_last_deploy(LAST_DEPLOY_PATH)
    summary = summarize_runtime(containers, last_deploy)
    return {
        **version,
        **summary,
        "applied_at_kst": pick_applied_at(
            last_deploy,
            summary.get("latest_restart"),
            version.get("git_date") or "",
        ),
        "containers": [
            {
                "id": c["id"],
                "short": c.get("short") or short_label(c["id"]),
                "status": c["status"],
                "started_at": c.get("started_at") or "",
                "started_at_kst": c.get("started_at_kst") or "",
                "image_id": c.get("image_id") or "",
                "image_created": c.get("image_created") or "",
                "image_created_kst": c.get("image_created_kst") or "",
            }
            for c in containers
        ],
    }




@router.post("/health/container-restart/{container_id}")
async def container_restart(
    container_id: str,
    _current_user=Depends(require_role("admin")),
) -> dict:
    """Restart a Docker container. Requires Docker socket."""
    allowed = {c["id"] for c in CONTAINER_OPTIONS}
    if container_id not in allowed:
        return {"error": f"Unknown container: {container_id}", "success": False}

    try:
        import docker
        client = docker.from_env()
        container = _find_container(client, container_id)
        if container is None:
            return {"error": f"Container {container_id} not found", "success": False}
        container.restart(timeout=30)
        label = next((c["label"] for c in CONTAINER_OPTIONS if c["id"] == container_id), container_id)
        logger.info(f"Container restarted: {container_id} ({label})")
        return {"success": True, "container": container_id, "label": label, "message": f"{label} restarted successfully"}
    except Exception as e:
        logger.warning(f"Container restart failed for {container_id}: {e}")
        return {"error": str(e), "success": False}


@router.get("/health/container-logs/{container_id}")
async def container_logs(
    container_id: str,
    tail: int = 500,
    _user=Depends(require_role("admin")),
) -> dict:
    """
    Fetch recent logs from a Docker container.
    Requires Docker socket mounted at /var/run/docker.sock.
    """
    allowed = {c["id"] for c in CONTAINER_OPTIONS}
    if container_id not in allowed:
        return {"error": f"Unknown container: {container_id}", "logs": ""}

    try:
        import docker
        client = docker.from_env()
        container = _find_container(client, container_id)
        if container is None:
            raise Exception(f"Container {container_id} not found")
        logs = container.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
        logs = _convert_log_timestamps_to_kst(logs)
        return {"container": container_id, "logs": logs}
    except Exception as e:
        logger.warning(f"Container logs failed for {container_id}: {e}")
        return {"container": container_id, "error": str(e), "logs": ""}


def _stream_docker_logs(container_id: str, tail: int, queue: "asyncio.Queue[str | None]", loop: asyncio.AbstractEventLoop):
    """Run in thread: stream Docker logs with follow=True, put decoded chunks into queue."""
    try:
        import docker
        client = docker.from_env()
        container = _find_container(client, container_id)
        if container is None:
            loop.call_soon_threadsafe(queue.put_nowait, None)
            return
        for chunk in container.logs(stream=True, follow=True, tail=tail, timestamps=True):
            decoded = chunk.decode("utf-8", errors="replace")
            if decoded:
                line_kst = _convert_log_timestamps_to_kst(decoded)
                loop.call_soon_threadsafe(queue.put_nowait, line_kst)
    except Exception as e:
        logger.warning(f"Container log stream failed for {container_id}: {e}")
    finally:
        loop.call_soon_threadsafe(queue.put_nowait, None)


@router.get("/health/container-logs/{container_id}/stream")
async def container_logs_stream(
    request: Request,
    container_id: str,
    tail: int = 100,
    _current_user=Depends(require_sse_role("admin")),
):
    """
    Stream container logs via SSE (tail -f style).
    Sends initial tail, then appends new lines as they arrive.
    EventSource cannot send headers, so auth uses get_sse_user (?ticket= preferred, or Bearer / deprecated ?token=).
    """
    allowed = {c["id"] for c in CONTAINER_OPTIONS}
    if container_id not in allowed:
        return {"error": f"Unknown container: {container_id}"}

    async def event_generator():
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)

        def run_stream():
            _stream_docker_logs(container_id, tail, queue, loop)

        future = executor.submit(run_stream)

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
                    continue
                if line is None:
                    break
                line_kst = _convert_log_timestamps_to_kst(line)
                yield {"event": "log", "data": line_kst}
        finally:
            future.cancel()

    return EventSourceResponse(event_generator())
