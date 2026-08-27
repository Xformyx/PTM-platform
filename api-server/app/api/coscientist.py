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
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.database import get_db
from app.dependencies import get_current_user, require_role
from app.models import Order
from app.models.order import OrderShare

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


async def _require_order_read(order_id: int, db: AsyncSession, user) -> Order:
    from app.api.orders import _check_order_access_async
    order = await _get_order_or_404(order_id, db)
    await _check_order_access_async(order, user, db)
    return order


async def _require_order_write(order_id: int, db: AsyncSession, user) -> Order:
    from app.api.orders import _require_write_access
    order = await _get_order_or_404(order_id, db)
    await _require_write_access(order, user, db)
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
    research_mode: str = "goal_led"  # goal_led | data_guided | hybrid
    rag_collections: Optional[List[str]] = None
    max_iterations: int = 3
    llm_provider: str = ""   # "" | "auto" | "ollama" | "openai" | "gemini"
    llm_model: str = ""      # e.g. "gemma3:27b", "gpt-4.1-mini"


class CoScientistMultiRunRequest(BaseModel):
    """Standalone multi-order run."""
    order_codes: List[str]
    research_goal: str = ""
    ptm_type: str = "phosphorylation"
    rag_collections: Optional[List[str]] = None
    max_iterations: int = 3
    llm_provider: str = ""
    llm_model: str = ""


class CoScientistFeedbackRequest(BaseModel):
    feedback_type: str = "direction"   # direction | constraint | seed_idea
    content: str


class CoScientistLabResultRequest(BaseModel):
    hypothesis_id: str
    outcome: str = "inconclusive"
    assay_type: str = ""
    result_summary: str = ""
    observed_effect: str = ""
    controls: List[str] = []
    source_reference: str = ""


async def _assert_session_for_order(order: Order, session_id: str) -> None:
    """Reject session IDs that do not belong to the requested order."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(_cs_url(f"/session/{session_id}"))
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Session not found")
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Failed to verify Co-Scientist session")
        codes = response.json().get("order_codes") or []
        if order.order_code not in codes:
            raise HTTPException(status_code=404, detail="Session not found for this order")
    except HTTPException:
        raise
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Co-Scientist API unavailable")
    except Exception as exc:
        logger.error("[CoScientist proxy] session bind check failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


def _build_data_grounded_seed(order: Order) -> str:
    """Build optional read-only prioritization context from platform PTM analyses."""
    kinase = order.kinase_analysis_data or {}
    heatmap = order.kinase_activity_heatmap or {}
    receptors = order.receptor_inference_data or {}
    lines = [
        "=== PTM-PLATFORM DATA-GROUNDED ANALYSIS SEED ===",
        "This is read-only prioritization context derived from measured PTM dynamics.",
        "Treat it as candidate directions; independently test alternatives and preserve falsifiability.",
        "",
    ]
    cascade = kinase.get("temporal_cascade") or kinase.get("cascade") or {}
    timepoints = cascade.get("timepoint_order") or cascade.get("timepoints") or []
    if timepoints:
        lines.append(f"Observed temporal order: {', '.join(map(str, timepoints[:12]))}")
    timepoint_map = cascade.get("timepoint_kinase_map") or cascade.get("kinases_by_timepoint") or {}
    if isinstance(timepoint_map, dict):
        for timepoint, kinases in list(timepoint_map.items())[:8]:
            if isinstance(kinases, list) and kinases:
                labels = [str(item.get("kinase") or item.get("name") or item) if isinstance(item, dict) else str(item) for item in kinases[:6]]
                lines.append(f"- {timepoint}: candidate active kinases {', '.join(labels)}")
    scores = heatmap.get("kinase_scores") or []
    if isinstance(scores, list) and scores:
        ranked = sorted(
            scores,
            key=lambda item: abs(float((item or {}).get("peak_score", (item or {}).get("score", 0)) or 0)) if isinstance(item, dict) else 0,
            reverse=True,
        )[:8]
        labels = [str(item.get("kinase") or item.get("name")) for item in ranked if isinstance(item, dict) and (item.get("kinase") or item.get("name"))]
        if labels:
            lines.append(f"Top data-supported kinase modules: {', '.join(labels)}")
    cowaves = heatmap.get("cowave_groups") or kinase.get("cowave_groups") or []
    if isinstance(cowaves, dict):
        cowaves = list(cowaves.values())
    if isinstance(cowaves, list) and cowaves:
        lines.append(f"Co-wave groups available for functional comparison: {len(cowaves)}")
    cross_layer = (
        kinase.get("temporal_ptm_protein_analysis")
        or heatmap.get("temporal_ptm_protein_analysis")
        or {}
    )
    if isinstance(cross_layer, dict) and cross_layer:
        lines.append(
            "Shared PTM–protein temporal evidence: "
            f"{cross_layer.get('cross_layer_edge_count', 0)} cross-layer edges; "
            f"{cross_layer.get('temporally_eligible_edge_count', 0)} temporally eligible; "
            f"kinase timing={cross_layer.get('kinase_timing_status', 'not_available')}; "
            f"dynamic co-wave={cross_layer.get('dynamic_co_wave_transition_status', 'not_available')}; "
            f"transition-supported Waves={cross_layer.get('dynamic_transition_supported_wave_count', 0)}; "
            f"observed pair transitions={cross_layer.get('dynamic_transition_pair_count', 0)}; "
            "all relationships are observational, not causal."
        )
        for edge in cross_layer.get("top_cross_layer_edges", [])[:6]:
            if not isinstance(edge, dict):
                continue
            lines.append(
                f"- Observational candidate: Wave {edge.get('source_wave_id')} → {edge.get('target_gene')} "
                f"(direction={edge.get('direction')}, peak_lag_min={edge.get('peak_lag_minutes')}, "
                f"temporally_eligible={edge.get('eligible_for_mechanism_chain')}, causality=not_tested)"
            )
    receptor_rows = receptors.get("receptors", receptors) if isinstance(receptors, dict) else receptors
    if isinstance(receptor_rows, list) and receptor_rows:
        names = [str(row.get("name") or row.get("gene") or "") for row in receptor_rows[:6] if isinstance(row, dict)]
        names = [name for name in names if name]
        if names:
            lines.append(f"Inferred upstream receptor candidates: {', '.join(names)}")
    lines.extend([
        "",
        "Prioritized questions:",
        "1. Which receptor–kinase–substrate mechanisms best explain the observed time-resolved PTM activity?",
        "2. Do local co-wave membership transitions support a testable change in temporal signaling organization without implying kinase switching?",
        "3. Which alternative mechanisms or counter-evidence should constrain each proposed pathway?",
        "=== END DATA-GROUNDED ANALYSIS SEED ===",
    ])
    return "\n".join(lines)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/orders/{order_id}/coscientist/health")
async def coscientist_health(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> JSONResponse:
    """Check if Co-Scientist API is reachable and return available ChromaDB collections."""
    await _require_order_read(order_id, db, user)
    return await _proxy_get("/health/detailed")


@router.post("/orders/{order_id}/coscientist/run")
async def coscientist_run(
    order_id: int,
    req: CoScientistRunRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> JSONResponse:
    """
    Start a new Co-Scientist session for this Order.

    The order_code and ptm_type are taken from the Order record automatically
    so the caller only needs to provide the research goal.
    """
    order = await _require_order_write(order_id, db, user)
    research_mode = req.research_mode if req.research_mode in {"goal_led", "data_guided", "hybrid"} else "goal_led"
    user_goal = req.research_goal.strip()
    seed = _build_data_grounded_seed(order)
    if research_mode == "data_guided":
        effective_goal = seed
    elif research_mode == "hybrid":
        effective_goal = (user_goal + "\n\n" if user_goal else "") + seed
    else:
        effective_goal = user_goal

    payload = {
        "order_codes": [order.order_code],
        "research_goal": effective_goal,
        "ptm_type": order.ptm_type or "phosphorylation",
        "rag_collections": req.rag_collections,
        "max_iterations": req.max_iterations,
        "llm_provider": req.llm_provider,
        "llm_model": req.llm_model,
    }
    response = await _proxy_post("/run", payload)
    logger.info(
        "[CoScientist] Started %s research for order=%s (goal=%s, seed_chars=%d)",
        research_mode, order.order_code, bool(user_goal), len(seed) if research_mode != "goal_led" else 0,
    )
    return response


@router.get("/orders/{order_id}/coscientist/sessions")
async def coscientist_sessions_for_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> JSONResponse:
    """List all Co-Scientist sessions for a specific order."""
    order = await _require_order_read(order_id, db, user)
    return await _proxy_get(f"/sessions?order_code={order.order_code}")


@router.get("/orders/{order_id}/coscientist/session/{session_id}")
async def coscientist_session(
    order_id: int,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> JSONResponse:
    """Poll the status and results of a Co-Scientist session."""
    order = await _require_order_read(order_id, db, user)
    await _assert_session_for_order(order, session_id)
    return await _proxy_get(f"/session/{session_id}")


@router.get("/orders/{order_id}/coscientist/session/{session_id}/discussion-packet")
async def coscientist_discussion_packet(
    order_id: int,
    session_id: str,
    max_hypotheses: int = Query(default=2, ge=1, le=5),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> JSONResponse:
    """Return the versioned, read-only Discussion Evidence Packet for one session."""
    order = await _require_order_read(order_id, db, user)
    await _assert_session_for_order(order, session_id)
    return await _proxy_get(
        f"/session/{session_id}/discussion-packet?max_hypotheses={max_hypotheses}"
    )


@router.post("/orders/{order_id}/coscientist/session/{session_id}/feedback")
async def coscientist_feedback(
    order_id: int,
    session_id: str,
    req: CoScientistFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> JSONResponse:
    """Submit scientist feedback to guide hypothesis evolution."""
    order = await _require_order_write(order_id, db, user)
    await _assert_session_for_order(order, session_id)
    payload = {
        "session_id": session_id,
        "feedback_type": req.feedback_type,
        "content": req.content,
    }
    return await _proxy_post(f"/session/{session_id}/feedback", payload)


@router.post("/orders/{order_id}/coscientist/session/{session_id}/cancel")
async def coscientist_cancel(
    order_id: int,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> JSONResponse:
    """Request cancellation of a running Co-Scientist session."""
    order = await _require_order_write(order_id, db, user)
    await _assert_session_for_order(order, session_id)
    return await _proxy_post(f"/session/{session_id}/cancel")


@router.post("/orders/{order_id}/coscientist/session/{session_id}/rerun")
async def coscientist_rerun(
    order_id: int,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> JSONResponse:
    """Re-run the pipeline incorporating accumulated scientist feedback."""
    order = await _require_order_write(order_id, db, user)
    await _assert_session_for_order(order, session_id)
    return await _proxy_post(f"/session/{session_id}/rerun")


@router.post("/orders/{order_id}/coscientist/session/{session_id}/design-experiments")
async def coscientist_design_experiments(
    order_id: int,
    session_id: str,
    top_n: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> JSONResponse:
    """Design experiments for the top hypotheses in a session."""
    order = await _require_order_write(order_id, db, user)
    await _assert_session_for_order(order, session_id)
    return await _proxy_post(
        f"/session/{session_id}/design-experiments?top_n={top_n}"
    )


@router.get("/orders/{order_id}/coscientist/session/{session_id}/scientific-reasoning")
async def coscientist_scientific_reasoning(
    order_id: int,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> JSONResponse:
    """Return graph, reflection, meta-review, and lab-result provenance."""
    order = await _require_order_read(order_id, db, user)
    await _assert_session_for_order(order, session_id)
    return await _proxy_get(f"/session/{session_id}/scientific-reasoning")


@router.post("/orders/{order_id}/coscientist/session/{session_id}/lab-results")
async def coscientist_lab_results(
    order_id: int,
    session_id: str,
    req: CoScientistLabResultRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> JSONResponse:
    """Record a researcher-observed lab outcome for a hypothesis."""
    order = await _require_order_write(order_id, db, user)
    await _assert_session_for_order(order, session_id)
    return await _proxy_post(f"/session/{session_id}/lab-results", req.model_dump())


# ─── Standalone multi-order endpoints (/api/coscientist/*) ───────────────────

@router.get("/coscientist/health")
async def coscientist_health_standalone(
    _user=Depends(require_role("admin", "analyst")),
) -> JSONResponse:
    """Check Co-Scientist service availability (standalone, no order context)."""
    return await _proxy_get("/health/detailed")


@router.get("/coscientist/orders")
async def coscientist_list_orders(
    ptm_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "analyst")),
) -> Dict[str, Any]:
    """
    List completed orders available for Co-Scientist synthesis.

    Returns minimal metadata (id, order_code, project_name, ptm_type, created_at)
    for orders the caller can access (admin: all; others: owned or shared).
    """
    conditions = [Order.status == "completed"]
    if ptm_type:
        conditions.append(Order.ptm_type == ptm_type)

    q = (
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
    is_admin = getattr(user, "role", "") == "admin"
    uid = getattr(user, "id", 0)
    if not is_admin and uid:
        q = q.outerjoin(
            OrderShare,
            (OrderShare.order_id == Order.id) & (OrderShare.shared_with_user_id == uid),
        ).where(or_(Order.user_id == uid, OrderShare.shared_with_user_id == uid))

    result = await db.execute(q)
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
async def coscientist_run_standalone(
    req: CoScientistMultiRunRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("admin", "analyst")),
) -> JSONResponse:
    """
    Start a multi-order Co-Scientist session.

    Synthesises PTM data from all specified orders and runs the full
    Generate → Debate → Evolve pipeline with cross-experiment context.
    """
    if not req.order_codes:
        raise HTTPException(status_code=422, detail="order_codes must not be empty")

    from app.api.orders import _require_write_access
    for code in req.order_codes:
        found = await db.execute(select(Order).where(Order.order_code == code))
        order = found.scalar_one_or_none()
        if order is None:
            raise HTTPException(status_code=404, detail=f"Order not found: {code}")
        await _require_write_access(order, user, db)

    payload = {
        "order_codes": req.order_codes,
        "research_goal": req.research_goal,
        "ptm_type": req.ptm_type,
        "rag_collections": req.rag_collections,
        "max_iterations": req.max_iterations,
        "llm_provider": req.llm_provider,
        "llm_model": req.llm_model,
    }
    return await _proxy_post("/run", payload)


@router.get("/coscientist/sessions")
async def coscientist_sessions_standalone(
    _user=Depends(require_role("admin", "analyst")),
) -> JSONResponse:
    """List all standalone Co-Scientist sessions."""
    return await _proxy_get("/sessions")


@router.get("/coscientist/session/{session_id}")
async def coscientist_session_standalone(
    session_id: str,
    _user=Depends(require_role("admin", "analyst")),
) -> JSONResponse:
    """Poll the status and results of a standalone Co-Scientist session."""
    return await _proxy_get(f"/session/{session_id}")


@router.post("/coscientist/session/{session_id}/feedback")
async def coscientist_feedback_standalone(
    session_id: str,
    req: CoScientistFeedbackRequest,
    _user=Depends(require_role("admin", "analyst")),
) -> JSONResponse:
    """Submit scientist feedback to a standalone session."""
    payload = {
        "session_id": session_id,
        "feedback_type": req.feedback_type,
        "content": req.content,
    }
    return await _proxy_post(f"/session/{session_id}/feedback", payload)


@router.post("/coscientist/session/{session_id}/cancel")
async def coscientist_cancel_standalone(
    session_id: str,
    _user=Depends(require_role("admin", "analyst")),
) -> JSONResponse:
    """Request cancellation of a running standalone Co-Scientist session."""
    return await _proxy_post(f"/session/{session_id}/cancel")


@router.post("/coscientist/session/{session_id}/rerun")
async def coscientist_rerun_standalone(
    session_id: str,
    _user=Depends(require_role("admin", "analyst")),
) -> JSONResponse:
    """Re-run a standalone session incorporating accumulated feedback."""
    return await _proxy_post(f"/session/{session_id}/rerun")


@router.post("/coscientist/session/{session_id}/design-experiments")
async def coscientist_design_experiments_standalone(
    session_id: str,
    top_n: int = Query(default=5, ge=1, le=20),
    _user=Depends(require_role("admin", "analyst")),
) -> JSONResponse:
    """Design experiments for a standalone session's top hypotheses."""
    return await _proxy_post(
        f"/session/{session_id}/design-experiments?top_n={top_n}"
    )


@router.get("/coscientist/session/{session_id}/scientific-reasoning")
async def coscientist_scientific_reasoning_standalone(
    session_id: str,
    _user=Depends(require_role("admin", "analyst")),
) -> JSONResponse:
    """Return graph, reflection, meta-review, and lab-result provenance."""
    return await _proxy_get(f"/session/{session_id}/scientific-reasoning")


@router.post("/coscientist/session/{session_id}/lab-results")
async def coscientist_lab_results_standalone(
    session_id: str,
    req: CoScientistLabResultRequest,
    _user=Depends(require_role("admin", "analyst")),
) -> JSONResponse:
    """Record a researcher-observed lab outcome for a standalone session."""
    return await _proxy_post(f"/session/{session_id}/lab-results", req.model_dump())
