"""Order-linked, strict-primary benchmark registration endpoints.

These endpoints create a metadata-only BenchmarkRun.  Starting the sanitized
snapshot and offline scoring is intentionally implemented in the next worker
phase so ordinary Orders cannot be changed by registration alone.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.orders import (
    _require_species_context,
    _require_write_access,
    _save_celery_task_id,
    global_kinase_modules,
    kinase_activity_heatmap,
)
from app.config import get_settings
from app.core.database import get_db
from app.dependencies import assert_not_viewer, get_current_user
from app.models.benchmark_run import BenchmarkRun
from app.models.order import Order
from app.services.benchmark_artifact import build_score_artifact, build_temporal_request
from app.services.benchmark_blind_context import (
    LINEAGE_CLASSES,
    build_blind_context,
    load_public_manifest,
    source_snapshot,
    validate_benchmark_eligibility,
)
from app.services.benchmark_run_lifecycle import (
    OFF_CONTRACT_CHILD_STATUSES,
    is_run_in_progress,
    overlay_run_status,
    run_phase,
    should_reuse_existing_run,
)
from app.services.benchmark_snapshot import create_sanitized_snapshot

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


class BenchmarkRunCreate(BaseModel):
    dataset_id: str = Field(default="insulin_signaling_v1", min_length=3, max_length=120)
    lineage_class: str


class _ServiceUser:
    """Minimal permission identity for server-side reuse of production endpoints."""

    def __init__(self, source_user: object) -> None:
        self.id = getattr(source_user, "id", None)
        self.role = getattr(source_user, "role", "admin")


def _serialize(run: BenchmarkRun, child: Order | None = None) -> dict:
    status, error_message = overlay_run_status(
        run.status,
        getattr(child, "status", None),
        getattr(child, "error_message", None),
        run.error_message,
    )
    payload = {
        "id": run.id,
        "run_code": run.run_code,
        "source_order_id": run.source_order_id,
        "benchmark_order_id": run.benchmark_order_id,
        "dataset_id": run.dataset_id,
        "status": status,
        "phase": run_phase(run.status, getattr(child, "status", None)),
        "production_contract": run.production_contract,
        "blind_policy": run.blind_policy,
        "blind_context": run.blind_context,
        "source_snapshot": run.source_snapshot,
        "score_summary": run.score_summary,
        "error_message": error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }
    if child is not None:
        payload["child_order"] = {
            "id": child.id,
            "order_code": child.order_code,
            "status": child.status,
            "progress_pct": float(child.progress_pct or 0),
            "current_stage": child.current_stage,
            "error_message": child.error_message,
        }
    return payload


async def _child_for_run(run: BenchmarkRun, db: AsyncSession) -> Order | None:
    if not run.benchmark_order_id:
        return None
    result = await db.execute(select(Order).where(Order.id == run.benchmark_order_id))
    return result.scalar_one_or_none()


async def _persist_overlay(run: BenchmarkRun, child: Order | None, db: AsyncSession) -> BenchmarkRun:
    dirty = False
    child_status = getattr(child, "status", None)
    if child is not None and child_status in OFF_CONTRACT_CHILD_STATUSES:
        child.status = "cancelled"
        child.stage_detail = "Cancelled: blind snapshot must not run RAG or report generation."
        child.error_message = None
        child_status = "cancelled"
        dirty = True
    status, error_message = overlay_run_status(
        run.status,
        child_status,
        getattr(child, "error_message", None),
        run.error_message,
    )
    if status != run.status or error_message != run.error_message:
        run.status = status
        run.error_message = error_message
        dirty = True
    if not dirty:
        return run
    await db.commit()
    await db.refresh(run)
    if child is not None:
        await db.refresh(child)
    return run


async def _source_order_or_404(order_id: int, user, db: AsyncSession) -> Order:
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Source Order not found")
    await _require_write_access(order, user, db)
    return order


@router.get("/lineage-options")
async def lineage_options(user=Depends(get_current_user)):
    return {"options": list(LINEAGE_CLASSES)}


@router.get("/source-orders/{order_id}/preflight")
async def benchmark_preflight(
    order_id: int,
    dataset_id: str = "insulin_signaling_v1",
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    order = await _source_order_or_404(order_id, user, db)
    try:
        manifest = load_public_manifest(dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    issues = validate_benchmark_eligibility(order, manifest=manifest)
    return {
        "eligible": not issues,
        "issues": issues,
        "dataset_id": dataset_id,
        "production_contract": manifest["production_contract"],
        "blind_policy": manifest["blind_policy"],
        "lineage_options": list(LINEAGE_CLASSES),
    }


@router.post("/source-orders/{order_id}/runs", status_code=201)
async def register_benchmark_run(
    order_id: int,
    body: BenchmarkRunCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    assert_not_viewer(user)
    order = await _source_order_or_404(order_id, user, db)
    try:
        manifest = load_public_manifest(body.dataset_id)
        issues = validate_benchmark_eligibility(order, manifest=manifest)
        if issues:
            raise ValueError("; ".join(issues))
        blind_context = build_blind_context(lineage_class=body.lineage_class, manifest=manifest)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing_rows = await db.execute(
        select(BenchmarkRun)
        .where(
            BenchmarkRun.source_order_id == order.id,
            BenchmarkRun.dataset_id == body.dataset_id,
        )
        .order_by(BenchmarkRun.created_at.desc())
    )
    for existing in existing_rows.scalars().all():
        child = await _child_for_run(existing, db)
        child_status = child.status if child else None
        if should_reuse_existing_run(existing.status, child_status) or is_run_in_progress(
            existing.status, child_status
        ):
            existing = await _persist_overlay(existing, child, db)
            return _serialize(existing, child)

    run = BenchmarkRun(
        run_code=f"BMR-{secrets.token_hex(8).upper()}",
        source_order_id=order.id,
        created_by_user_id=getattr(user, "id", None),
        dataset_id=body.dataset_id,
        manifest_sha256=manifest["manifest_sha256"],
        production_contract=manifest["production_contract"],
        blind_policy=manifest["blind_policy"],
        blind_context=blind_context,
        source_snapshot=source_snapshot(order, manifest=manifest),
        status="registered",
        provenance={"registration_mode": "order_detail_strict_primary"},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return _serialize(run)


@router.get("/source-orders/{order_id}/runs")
async def list_benchmark_runs(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    await _source_order_or_404(order_id, user, db)
    rows = await db.execute(
        select(BenchmarkRun)
        .where(BenchmarkRun.source_order_id == order_id)
        .order_by(BenchmarkRun.created_at.desc())
    )
    runs = []
    for run in rows.scalars().all():
        child = await _child_for_run(run, db)
        run = await _persist_overlay(run, child, db)
        runs.append(_serialize(run, child))
    return {"runs": runs}


@router.get("/runs/{run_id}")
async def get_benchmark_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(select(BenchmarkRun).where(BenchmarkRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="BenchmarkRun not found")
    await _source_order_or_404(run.source_order_id, user, db)
    child = await _child_for_run(run, db)
    run = await _persist_overlay(run, child, db)
    return _serialize(run, child)


@router.post("/runs/{run_id}/start")
async def start_benchmark_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Create a header-sanitized child Order and run 0층 preprocessing only."""

    assert_not_viewer(user)
    result = await db.execute(select(BenchmarkRun).where(BenchmarkRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="BenchmarkRun not found")
    source = await _source_order_or_404(run.source_order_id, user, db)

    child = None
    if run.benchmark_order_id:
        child_result = await db.execute(select(Order).where(Order.id == run.benchmark_order_id))
        child = child_result.scalar_one_or_none()

    restartable = run.status == "registered" or (
        run.status in {"preprocessing", "failed"}
        and (child is None or child.status in {"failed", "queued", "cancelled"})
    )
    if not restartable:
        raise HTTPException(status_code=409, detail=f"BenchmarkRun cannot start from status {run.status}")

    settings = get_settings()
    snapshot_dir = Path(settings.INPUT_DIR) / "benchmark_runs" / run.run_code
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    try:
        snapshot = await asyncio.to_thread(
            create_sanitized_snapshot,
            source_order=source,
            blind_context=run.blind_context,
            destination_dir=snapshot_dir,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not create blind snapshot: {exc}") from exc

    child_fields = {
        "order_code": f"bm_{run.run_code.lower()}",
        "user_id": source.user_id,
        "run_by_user_id": getattr(user, "id", None),
        "project_name": "Blind benchmark analysis",
        "status": "queued",
        "ptm_type": source.ptm_type,
        "species": source.species,
        "organism_code": source.organism_code,
        "sample_config": snapshot.sample_config,
        "pr_matrix_path": snapshot.pr_matrix_path,
        "pg_matrix_path": snapshot.pg_matrix_path,
        "fasta_path": snapshot.fasta_path,
        "config_xlsx_path": None,
        "analysis_context": {
            "cell_type": run.blind_context["cell_context"]["lineage_class"],
            "treatment": run.blind_context["treatment_label"],
            "time_points": [],
            "biological_question": "",
            "special_conditions": "",
            "benchmark_blind_mode": True,
        },
        "analysis_options": {
            "benchmark_blind_mode": True,
            "source_order_id": source.id,
            "benchmark_run_id": run.id,
        },
        "report_options": {"temporal_contract": run.production_contract["temporal_contract"]},
        "rag_collections": None,
        "error_message": None,
        "stage_detail": None,
        "progress_pct": 0,
        "current_stage": None,
    }
    if child is None:
        child = Order(**child_fields)
        db.add(child)
        await db.flush()
    else:
        for key, value in child_fields.items():
            if key == "order_code":
                continue
            setattr(child, key, value)
        await db.flush()

    run.benchmark_order_id = child.id
    run.status = "preprocessing"
    run.error_message = None
    run.provenance = {
        **(run.provenance or {}),
        "blind_snapshot_input_sha256": snapshot.input_sha256,
        "source_input_headers_replaced": True,
        "rag_used": False,
        "llm_used": False,
    }
    await db.commit()
    await db.refresh(run)
    await db.refresh(child)

    species_context = _require_species_context(child.species)
    task_config = {
        "order_code": child.order_code,
        "pr_matrix_path": child.pr_matrix_path,
        "pg_matrix_path": child.pg_matrix_path,
        "fasta_path": child.fasta_path,
        "ptm_mode": "phospho",
        "condition_map": snapshot.condition_map,
        "single_time_point": False,
        "species_tax_id": species_context.taxonomy_id,
        "kegg_organism": species_context.kegg_organism,
        "species": species_context.analysis_species,
        "species_label": species_context.label,
        "custom_reference": species_context.custom_reference,
        "analysis_options": {"benchmark_blind_mode": True},
        "experimental_context": {
            **run.blind_context,
            "organism": species_context.analysis_species,
            "ptm_type": source.ptm_type,
        },
        "research_questions": [],
        "chromadb_collections": [],
        "chain_to_next": False,
        "temporal_contract": run.production_contract["temporal_contract"],
        "benchmark_run_id": run.id,
    }
    from celery import Celery

    celery_app = Celery("ptm_workers")
    celery_app.conf.broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
    celery_app.conf.result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
    task = celery_app.send_task(
        "preprocessing.tasks.run_preprocessing",
        args=[child.id, task_config],
        queue="preprocessing",
    )
    await _save_celery_task_id(child.id, task.id)
    return {**_serialize(run, child), "preprocessing_task_id": task.id}


@router.post("/runs/{run_id}/run-temporal-analysis")
async def run_benchmark_temporal_analysis(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Use the same production global-module and full TMM endpoints on the child."""

    assert_not_viewer(user)
    result = await db.execute(select(BenchmarkRun).where(BenchmarkRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="BenchmarkRun not found")
    source = await _source_order_or_404(run.source_order_id, user, db)
    if not run.benchmark_order_id:
        raise HTTPException(status_code=409, detail="BenchmarkRun has no sanitized child Order")
    child_result = await db.execute(select(Order).where(Order.id == run.benchmark_order_id))
    child = child_result.scalar_one_or_none()
    if not child or child.status != "completed":
        raise HTTPException(status_code=409, detail="Blind preprocessing must complete before temporal analysis")
    if run.status not in {"preprocessing", "temporal_analysis", "failed"}:
        raise HTTPException(status_code=409, detail=f"BenchmarkRun cannot run temporal analysis from {run.status}")

    settings = get_settings()
    output_dir = Path(settings.OUTPUT_DIR) / child.order_code
    run.status = "temporal_analysis"
    run.error_message = None
    await db.commit()
    await db.refresh(run)
    try:
        temporal_request = build_temporal_request(output_dir=output_dir, ptm_type=child.ptm_type)
        service_user = _ServiceUser(user)
        annotated = await global_kinase_modules(
            child.id,
            {
                "ptms": temporal_request["ptms"],
                "cowave_modules": temporal_request["cowave_modules"],
                "force_refresh": True,
            },
            db,
            service_user,
        )
        tmm_modules = [
            {
                "kinase": module.get("canonical") or module.get("kinase"),
                "ptms": [
                    {"gene": member.get("gene"), "position": member.get("position")}
                    for member in module.get("members", [])
                    if member.get("gene") and member.get("position")
                ],
            }
            for module in annotated.get("kinase_modules", [])
        ]
        tmm = await kinase_activity_heatmap(
            child.id,
            {"kinase_modules": tmm_modules, "force_refresh": True},
            db,
            service_user,
        )
        artifact = build_score_artifact(
            output_dir=output_dir,
            fasta_path=Path(child.fasta_path),
            ptm_type=child.ptm_type,
            production_contract=run.production_contract,
            tmm_result=tmm,
        )
        artifact_path = output_dir / "benchmark_blind_analysis_artifact.json"
        artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        run.status = "failed"
        run.error_message = f"Blind temporal analysis failed: {exc}"[:2000]
        await db.commit()
        await db.refresh(run)
        raise HTTPException(status_code=500, detail=run.error_message) from exc

    run.artifact_path = str(artifact_path)
    run.status = "scoring_queued"
    run.provenance = {**(run.provenance or {}), "tmm_full_temporal_completed": True}
    await db.commit()
    await db.refresh(run)
    from celery import Celery

    celery_app = Celery("ptm_benchmark_runner")
    celery_app.conf.broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
    celery_app.conf.result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
    task = celery_app.send_task("benchmarking.tasks.score_benchmark_run", args=[run.id], queue="benchmark")
    return {**_serialize(run, child), "scoring_task_id": task.id}
