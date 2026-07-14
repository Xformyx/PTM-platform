"""
Co-Scientist Proxy Router.

Two sets of endpoints:
  1. /api/orders/{order_id}/coscientist/*  — scoped to a single Order (legacy)
  2. /api/coscientist/*                    — standalone, multi-order synthesis
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
    """Single-order run (scoped to one Order record)."""
    research_goal: str = ""
    rag_collections: Optional[List[str]] = None
    max_iterations: int = 3


class CoScientistMultiRunRequest(BaseModel):
    """Standalone multi-order run."""
    order_codes: List[str]
    research_goal: str = ""
    ptm_type: str = "phosphorylation"
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


# ─── Standalone multi-order endpoints (/api/coscientist/*) ───────────────────

@router.get("/coscientist/health")
async def coscientist_health_standalone() -> JSONResponse:
    """Check Co-Scientist service availability (standalone, no order context)."""
    return await _proxy_get("/health/detailed")


@router.get("/coscientist/orders")
async def coscientist_list_orders(
    ptm_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    List completed orders available for Co-Scientist synthesis.

    Returns minimal metadata (id, order_code, project_name, ptm_type, created_at)
    for all orders with status='completed'.
    """
    from sqlalchemy import and_

    conditions = [Order.status == "completed"]
    if ptm_type:
        conditions.append(Order.ptm_type == ptm_type)

    result = await db.execute(
        select(
            Order.id,
            Order.order_code,
            Order.project_name,
            Order.ptm_type,
            Order.created_at,
            Order.species,
        )
        .where(and_(*conditions))
        .order_by(Order.created_at.desc())
        .limit(200)
    )
    rows = result.fetchall()
    return {
        "orders": [
            {
                "id": r.id,
                "order_code": r.order_code,
                "project_name": r.project_name,
                "ptm_type": r.ptm_type,
                "species": r.species,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.post("/coscientist/run")
async def coscientist_run_standalone(req: CoScientistMultiRunRequest) -> JSONResponse:
    """
    Start a multi-order Co-Scientist session.

    Synthesises PTM data from all specified orders and runs the full
    Generate → Debate → Evolve pipeline with cross-experiment context.
    """
    if not req.order_codes:
        raise HTTPException(status_code=422, detail="order_codes must not be empty")

    payload = {
        "order_codes": req.order_codes,
        "research_goal": req.research_goal,
        "ptm_type": req.ptm_type,
        "rag_collections": req.rag_collections,
        "max_iterations": req.max_iterations,
    }
    return await _proxy_post("/run", payload)


@router.get("/coscientist/session/{session_id}")
async def coscientist_session_standalone(session_id: str) -> JSONResponse:
    """Poll the status and results of a standalone Co-Scientist session."""
    return await _proxy_get(f"/session/{session_id}")


@router.post("/coscientist/session/{session_id}/feedback")
async def coscientist_feedback_standalone(
    session_id: str,
    req: CoScientistFeedbackRequest,
) -> JSONResponse:
    """Submit scientist feedback to a standalone session."""
    payload = {
        "session_id": session_id,
        "feedback_type": req.feedback_type,
        "content": req.content,
    }
    return await _proxy_post(f"/session/{session_id}/feedback", payload)


@router.post("/coscientist/session/{session_id}/rerun")
async def coscientist_rerun_standalone(session_id: str) -> JSONResponse:
    """Re-run a standalone session incorporating accumulated feedback."""
    return await _proxy_post(f"/session/{session_id}/rerun")


@router.post("/coscientist/session/{session_id}/design-experiments")
async def coscientist_design_experiments_standalone(
    session_id: str,
    top_n: int = Query(default=5, ge=1, le=20),
) -> JSONResponse:
    """Design experiments for a standalone session's top hypotheses."""
    return await _proxy_post(
        f"/session/{session_id}/design-experiments?top_n={top_n}"
    )
