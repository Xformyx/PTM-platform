"""
PPTX generation API — dispatches long-running work to Celery (report_generation queue).

Avoids HTTP 524 (Cloudflare ~100s timeout) by returning immediately with task_id;
client polls GET .../generate-pptx/status/{task_id}.
"""

import logging
import os
from pathlib import Path

from celery import Celery
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.orders import _check_order_access_async, _require_write_access
from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.dependencies import get_current_user
from app.models.order import Order

_PPTX_TASK_TTL = 24 * 3600

router = APIRouter(prefix="/orders", tags=["presentation"])
logger = logging.getLogger("ptm-platform.presentation")

MAX_REPORT_CHARS = 12000


def _load_report_text(output_dir: Path, file_suffix: str) -> str:
    """Load the most recent report MD (for pre-flight check)."""
    candidates = sorted(
        output_dir.glob("*_report_*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        text = candidates[0].read_text(encoding="utf-8", errors="replace")
        return text[:MAX_REPORT_CHARS]
    for name in (f"comprehensive_report{file_suffix}.md", "final_report.md", "report.md"):
        alt = output_dir / name
        if alt.exists():
            return alt.read_text(encoding="utf-8", errors="replace")[:MAX_REPORT_CHARS]
    return ""


def _celery_app() -> Celery:
    app = Celery("ptm_workers")
    app.conf.broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
    app.conf.result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
    return app


class GeneratePptxRequest(BaseModel):
    llm_provider: str = "ollama"
    llm_model: str = ""


@router.post("/{order_id}/generate-pptx")
async def generate_pptx(
    order_id: int,
    body: GeneratePptxRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user=Depends(get_current_user),
):
    """Queue PPTX generation; returns task_id for polling (fast response — no 524)."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    await _require_write_access(order, user, db)

    if body.llm_provider not in ("gemini", "openai", "ollama"):
        raise HTTPException(
            status_code=400,
            detail=f"PPTX는 provider '{body.llm_provider}'를 지원하지 않습니다. Ollama, Gemini, OpenAI 중에서 선택하세요.",
        )

    output_dir = Path(settings.OUTPUT_DIR) / (order.order_code or str(order.id))
    if not output_dir.exists():
        raise HTTPException(status_code=400, detail="No analysis output found for this order")

    file_suffix = "_phospho" if (order.ptm_type or "phosphorylation") == "phosphorylation" else "_ubi"
    report_text = _load_report_text(output_dir, file_suffix)
    if not report_text:
        raise HTTPException(status_code=400, detail="No report found. Run Report Generation first.")

    celery_app = _celery_app()
    task = celery_app.send_task(
        "pptx_generation.tasks.run_pptx_generation",
        args=[order_id, body.llm_provider, body.llm_model or ""],
        queue="report_generation",
    )
    redis = await get_redis()
    await redis.set(f"pptx_task:{order_id}:{task.id}", "1", ex=_PPTX_TASK_TTL)

    logger.info(
        "[PPTX] queued order=%s task_id=%s provider=%s",
        order.order_code,
        task.id,
        body.llm_provider,
    )

    return {
        "status": "queued",
        "task_id": task.id,
        "message": "작업이 백그라운드에서 실행됩니다. 완료까지 페이지를 이동해도 됩니다.",
    }


@router.get("/{order_id}/generate-pptx/status/{task_id}")
async def generate_pptx_status(
    order_id: int,
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Poll Celery task state for PPTX generation."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Raises 403 if no access. A share level string is success, not an error.
    await _check_order_access_async(order, user, db)

    redis = await get_redis()
    bound = await redis.get(f"pptx_task:{order_id}:{task_id}")
    if not bound:
        raise HTTPException(status_code=404, detail="PPTX task not found for this order")

    celery_app = _celery_app()
    ar = AsyncResult(task_id, app=celery_app)
    state = ar.state

    if state == "PROGRESS":
        meta = ar.info if isinstance(ar.info, dict) else {}
        return {
            "job_status": "running",
            "ready": False,
            "celery_state": state,
            "stage": meta.get("stage"),
            "message": meta.get("message"),
            "progress": meta.get("progress"),
        }

    if state in ("PENDING", "RECEIVED", "STARTED", "RETRY"):
        return {
            "job_status": "running",
            "celery_state": state,
            "ready": False,
            "message": "Waiting for worker…" if state == "PENDING" else None,
            "progress": None,
        }

    if state == "SUCCESS":
        payload = ar.result
        if isinstance(payload, dict) and payload.get("status") == "ok":
            return {
                "job_status": "success",
                "ready": True,
                "filename": payload.get("filename"),
                "slide_count": payload.get("slide_count"),
                "figures_embedded": payload.get("figures_embedded", []),
            }
        return {
            "job_status": "success",
            "ready": True,
            "filename": None,
            "raw": payload,
        }

    if state == "FAILURE":
        exc = ar.result
        msg = str(ar.info) if ar.info is not None else str(exc)
        if isinstance(exc, Exception):
            msg = str(exc)
        return {
            "job_status": "failure",
            "ready": True,
            "error": msg or "PPTX generation failed",
        }

    return {
        "job_status": "unknown",
        "celery_state": state,
        "ready": False,
    }
