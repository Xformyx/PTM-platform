"""
Co-Scientist Proxy Router.

Forwards requests from PTM-platform to the Co-Scientist API service
(ptm-coscientist-api), scoping each call to a specific Order.

All endpoints are mounted under /api/orders/{order_id}/coscientist/
"""

import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.database import get_db
from app.models import Order

logger = logging.getLogger(__name__)
router = APIRouter()

_TIMEOUT = httpx.Timeout(10.0, read=300.0)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _cs_url(path: str) -> str:
    base = get_settings().COSCIENTIST_API_URL.rstrip("/")
    return f"{base}{path}"


async def _get_order_or_404(order_id: int, db: AsyncSession) -> Order:
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


async def _proxy_get(path: str) -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(_cs_url(path))
        return JSONResponse(content=r.json(), status_code=r.status_code)
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Co-Scientist API unavailable")
    except Exception as e:
        logger.error(f"[CoScientist proxy] GET {path} failed: {e}")
        raise HTTPException(status_code=502, detail=str(e))


async def _proxy_post(path: str, body: Any = None) -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(_cs_url(path), json=body)
        return JSONResponse(content=r.json(), status_code=r.status_code)
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Co-Scientist API unavailable")
    except Exception as e:
        logger.error(f"[CoScientist proxy] POST {path} failed: {e}")
        raise HTTPException(status_code=502, detail=str(e))


# ─── Request models ───────────────────────────────────────────────────────────

class CoScientistRunRequest(BaseModel):
    research_goal: str = ""
    rag_collections: Optional[List[str]] = None
    max_iterations: int = 3


class CoScientistFeedbackRequest(BaseModel):
    feedback_type: str = "direction"   # direction | constraint | seed_idea
    content: str


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/orders/{order_id}/coscientist/health")
async def coscientist_health(
    order_id: int,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Check if Co-Scientist API is reachable and return available ChromaDB collections."""
    await _get_order_or_404(order_id, db)
    return await _proxy_get("/health/detailed")


@router.post("/orders/{order_id}/coscientist/run")
async def coscientist_run(
    order_id: int,
    req: CoScientistRunRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Start a new Co-Scientist session for this Order.

    The order_code and ptm_type are taken from the Order record automatically
    so the caller only needs to provide the research goal.
    """
    order = await _get_order_or_404(order_id, db)

    payload = {
        "order_code": order.order_code,
        "research_goal": req.research_goal,
        "ptm_type": order.ptm_type or "phosphorylation",
        "rag_collections": req.rag_collections,
        "max_iterations": req.max_iterations,
    }
    return await _proxy_post("/run", payload)


@router.get("/orders/{order_id}/coscientist/session/{session_id}")
async def coscientist_session(
    order_id: int,
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Poll the status and results of a Co-Scientist session."""
    await _get_order_or_404(order_id, db)
    return await _proxy_get(f"/session/{session_id}")


@router.post("/orders/{order_id}/coscientist/session/{session_id}/feedback")
async def coscientist_feedback(
    order_id: int,
    session_id: str,
    req: CoScientistFeedbackRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Submit scientist feedback to guide hypothesis evolution."""
    await _get_order_or_404(order_id, db)
    payload = {
        "session_id": session_id,
        "feedback_type": req.feedback_type,
        "content": req.content,
    }
    return await _proxy_post(f"/session/{session_id}/feedback", payload)


@router.post("/orders/{order_id}/coscientist/session/{session_id}/rerun")
async def coscientist_rerun(
    order_id: int,
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Re-run the pipeline incorporating accumulated scientist feedback."""
    await _get_order_or_404(order_id, db)
    return await _proxy_post(f"/session/{session_id}/rerun")


@router.post("/orders/{order_id}/coscientist/session/{session_id}/design-experiments")
async def coscientist_design_experiments(
    order_id: int,
    session_id: str,
    top_n: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Design experiments for the top hypotheses in a session."""
    await _get_order_or_404(order_id, db)
    return await _proxy_post(
        f"/session/{session_id}/design-experiments?top_n={top_n}"
    )
