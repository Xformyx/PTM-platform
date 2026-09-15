"""Runtime banner for sidebar: version vs live container start/image times.

This is platform operations display only. It does not change measured
research quantities or report claims.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
CLUSTER_WINDOW = timedelta(seconds=90)
LAST_DEPLOY_PATH = Path("/app/data/.last-dev-deploy.json")

# Compose service name or container id → short sidebar label
SHORT_LABELS = {
    "ptm-worker-preprocessing": "Preprocess",
    "ptm-worker-rag": "RAG",
    "ptm-worker-report": "Report",
    "ptm-celery-beat": "Beat",
    "ptm-api-server": "API",
    "ptm-mcp-server": "MCP",
    "ptm-gateway": "Gateway",
    "ptm-frontend": "UI",
    "ptm-mysql": "MySQL",
    "ptm-redis": "Redis",
    "ptm-chromadb": "Chroma",
    "ptm-coscientist-api": "CoScientist",
    "ptm-benchmark-runner": "Bench",
    "ptm-benchmark-tmm-runner": "TMM",
    "celery-worker-preprocessing": "Preprocess",
    "celery-worker-rag": "RAG",
    "celery-worker-report": "Report",
    "api-server": "API",
    "mcp-server": "MCP",
    "frontend": "UI",
    "gateway": "Gateway",
    "benchmark-runner": "Bench",
    "benchmark-tmm-runner": "TMM",
}

INFRA_IDS = frozenset({"ptm-mysql", "ptm-redis", "ptm-chromadb"})


def short_label(name: str) -> str:
    return SHORT_LABELS.get(name, name.replace("ptm-", "").replace("celery-worker-", ""))


def parse_docker_ts(raw: str) -> datetime | None:
    """Parse Docker RFC3339 / ISO stamps, including nanosecond fractions."""
    text = (raw or "").strip()
    if not text or text.startswith("0001-01-01"):
        return None
    text = text.replace("Z", "+00:00")
    if "." in text:
        head, tail = text.split(".", 1)
        frac = ""
        tz = ""
        for i, ch in enumerate(tail):
            if ch.isdigit():
                frac += ch
            else:
                tz = tail[i:]
                break
        frac = (frac + "000000")[:6]
        text = f"{head}.{frac}{tz}"
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt


def format_kst(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")


_KST_WALL = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def parse_display_ts(raw: str) -> datetime | None:
    """Parse Docker ISO or a naive KST wall clock used in the sidebar.

    ``YYYY-MM-DD HH:MM:SS`` is already Asia/Seoul (format_kst / format_git_date_kst).
    Treating it as UTC would shift the footer by +9 hours.
    """
    text = (raw or "").strip()
    if not text:
        return None
    if _KST_WALL.match(text):
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
    return parse_docker_ts(text)


def pick_applied_at(
    last_deploy: dict[str, Any] | None = None,
    latest_restart: dict[str, Any] | None = None,
    git_date: str = "",
) -> str:
    """Newest of deploy event, live container start, or written GIT_DATE.

    GIT_DATE used to store the commit clock, which is why the sidebar could
    freeze at 00:30 after a morning restart. Prefer live/deploy stamps.
    """
    candidates: list[datetime] = []
    for raw in (
        (last_deploy or {}).get("at"),
        (last_deploy or {}).get("at_kst"),
        (latest_restart or {}).get("at"),
        (latest_restart or {}).get("at_kst"),
        git_date,
    ):
        dt = parse_display_ts(str(raw or ""))
        if dt is not None:
            candidates.append(dt)
    if not candidates:
        return ""
    return format_kst(max(candidates))


def load_last_deploy(path: Path | None = None) -> dict[str, Any] | None:
    target = path or LAST_DEPLOY_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    at = parse_docker_ts(str(raw.get("at") or ""))
    built = [str(x) for x in (raw.get("built") or []) if x]
    restarted = [str(x) for x in (raw.get("restarted") or []) if x]
    return {
        "at": at.isoformat() if at else str(raw.get("at") or ""),
        "at_kst": format_kst(at),
        "kind": str(raw.get("kind") or "deploy"),
        "commit": str(raw.get("commit") or ""),
        "version": str(raw.get("version") or ""),
        "built": built,
        "built_labels": [short_label(x) for x in built],
        "restarted": restarted,
        "restarted_labels": [short_label(x) for x in restarted],
    }


def _latest_cluster(
    rows: list[dict[str, Any]],
    time_key: str,
    *,
    exclude_ids: frozenset[str] | None = None,
) -> dict[str, Any] | None:
    dated: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        if exclude_ids and row.get("id") in exclude_ids:
            continue
        dt = parse_docker_ts(str(row.get(time_key) or ""))
        if dt is None:
            continue
        dated.append((dt, row))
    if not dated:
        return None
    dated.sort(key=lambda item: item[0], reverse=True)
    newest = dated[0][0]
    cluster = [row for dt, row in dated if newest - dt <= CLUSTER_WINDOW]
    return {
        "at": newest.isoformat(),
        "at_kst": format_kst(newest),
        "ids": [row["id"] for row in cluster],
        "labels": [row.get("short") or short_label(str(row["id"])) for row in cluster],
    }


def summarize_runtime(
    containers: list[dict[str, Any]],
    last_deploy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pick the newest app/pipeline restart cluster and newest image cluster."""
    latest_restart = _latest_cluster(containers, "started_at", exclude_ids=INFRA_IDS)
    if latest_restart is None:
        latest_restart = _latest_cluster(containers, "started_at")
    latest_image = _latest_cluster(containers, "image_created", exclude_ids=INFRA_IDS)
    if latest_image is None:
        latest_image = _latest_cluster(containers, "image_created")
    return {
        "last_deploy": last_deploy,
        "latest_restart": latest_restart,
        "latest_image": latest_image,
    }
