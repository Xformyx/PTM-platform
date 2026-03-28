import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.database import get_db
from app.core.webhook import send_order_webhook
from app.dependencies import get_current_user
from app.models.order import Order, OrderLog
from app.models.rag_collection import RagCollection
from app.models.user import User

router = APIRouter(prefix="/orders", tags=["orders"])
logger = logging.getLogger("ptm-platform.orders")


def _resolve_fasta(reference_dir: str, species: str) -> str | None:
    """Find the first .fasta/.fa file under reference_dir/<species>/."""
    from pathlib import Path

    species_dir = Path(reference_dir) / species.lower()
    if not species_dir.is_dir():
        return None
    for f in sorted(species_dir.iterdir()):
        if f.suffix in (".fasta", ".fa") and f.is_file():
            return str(f)
    return None


def _validate_order_code(code: str) -> None:
    """Validate order code for safe use as directory name."""
    import re
    if not code or len(code) > 64:
        raise HTTPException(status_code=400, detail="Order name must be 1–64 characters")
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", code):
        raise HTTPException(
            status_code=400,
            detail="Order name may only contain letters, numbers, hyphens, underscores, and periods",
        )


def _build_condition_map(sample_cfg: dict | list | None) -> dict:
    """Build {filename: condition_label} from sample_config.

    The preprocessing code expects:
      - "Control" for control samples
      - condition label (e.g. "3h", "6h") for treatment samples
    """
    condition_map = {}
    if not sample_cfg:
        return condition_map

    samples = []
    if isinstance(sample_cfg, dict):
        samples = sample_cfg.get("samples", [])
    elif isinstance(sample_cfg, list):
        samples = sample_cfg

    for entry in samples:
        fname = entry.get("file_name") or entry.get("File_Name", "")
        if not fname:
            continue

        group = (entry.get("group") or entry.get("Group", "")).strip()
        condition = (entry.get("condition") or entry.get("Condition", "")).strip()
        replicate = entry.get("replicate") or entry.get("Replicate")

        if group.lower() == "control":
            condition_map[fname] = "Control"
        elif condition:
            # Strip replicate suffix for grouping (e.g. "6h_3" → "6h")
            cond_group = condition
            if replicate is not None:
                suffix = f"_{replicate}"
                if cond_group.endswith(suffix):
                    cond_group = cond_group[: -len(suffix)]
            condition_map[fname] = cond_group if cond_group else condition
        elif group:
            condition_map[fname] = group
        else:
            condition_map[fname] = "Unknown"

    return condition_map


# ── List / Get ───────────────────────────────────────────────────────────────

@router.get("")
async def list_orders(
    status_filter: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    # Alias for creator and runner
    CreatorUser = User.__table__.alias("creator")
    RunnerUser = User.__table__.alias("runner")

    base_query = (
        select(
            Order,
            CreatorUser.c.name.label("created_by_name"),
            RunnerUser.c.name.label("run_by_name"),
        )
        .outerjoin(CreatorUser, Order.user_id == CreatorUser.c.id)
        .outerjoin(RunnerUser, Order.run_by_user_id == RunnerUser.c.id)
        .order_by(Order.created_at.desc())
    )
    if status_filter:
        base_query = base_query.where(Order.status == status_filter)
    if getattr(user, "role", "admin") != "admin":
        base_query = base_query.where(Order.user_id == user.id)

    query = base_query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = result.all()

    count_query = select(sqlfunc.count(Order.id))
    if status_filter:
        count_query = count_query.where(Order.status == status_filter)
    if getattr(user, "role", "admin") != "admin":
        count_query = count_query.where(Order.user_id == user.id)
    count_result = await db.execute(count_query)
    total = count_result.scalar()

    return {
        "orders": [
            {
                "id": o.id,
                "order_code": o.order_code,
                "project_name": o.project_name,
                "status": o.status,
                "ptm_type": o.ptm_type,
                "species": o.species,
                "progress_pct": float(o.progress_pct),
                "current_stage": o.current_stage,
                "stage_detail": o.stage_detail,
                "error_message": o.error_message,
                "started_at": o.started_at.isoformat() + "Z" if o.started_at else None,
                "created_at": o.created_at.isoformat() + "Z",
                "completed_at": o.completed_at.isoformat() + "Z" if o.completed_at else None,
                "created_by": created_by_name,
                "run_by": run_by_name,
            }
            for o, created_by_name, run_by_name in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _check_order_access(order, user):
    """Raise 403 if non-admin user tries to access another user's order."""
    if getattr(user, "role", "admin") != "admin" and order.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this order")


@router.get("/{order_id}")
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    return {
        "id": order.id,
        "order_code": order.order_code,
        "project_name": order.project_name,
        "status": order.status,
        "ptm_type": order.ptm_type,
        "species": order.species,
        "organism_code": order.organism_code,
        "sample_config": order.sample_config,
        "analysis_context": order.analysis_context,
        "analysis_options": order.analysis_options,
        "report_options": order.report_options,
        "rag_collections": order.rag_collections,
        "current_stage": order.current_stage,
        "progress_pct": float(order.progress_pct),
        "stage_detail": order.stage_detail,
        "result_files": order.result_files,
        "error_message": order.error_message,
        "cross_talk_data": order.cross_talk_data,
        "signal_propagation_data": order.signal_propagation_data,
        "started_at": order.started_at.isoformat() + "Z" if order.started_at else None,
        "completed_at": order.completed_at.isoformat() + "Z" if order.completed_at else None,
        "created_at": order.created_at.isoformat() + "Z",
    }


class UpdateOrderOptionsRequest(BaseModel):
    analysis_context: Optional[dict] = None
    analysis_options: Optional[dict] = None
    report_options: Optional[dict] = None
    rag_collections: Optional[list] = None


@router.patch("/{order_id}")
async def update_order_options(
    order_id: int,
    body: UpdateOrderOptionsRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Update analysis_context, analysis_options, and/or report_options for an order.
    Used before re-run or restart to allow re-configuration of Analysis Focus and Report Options."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)
    if order.status not in ("pending", "completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update order while running (status: '{order.status}'). Stop first.",
        )
    if body.analysis_context is not None:
        order.analysis_context = body.analysis_context
    if body.analysis_options is not None:
        order.analysis_options = body.analysis_options
    if body.report_options is not None:
        order.report_options = body.report_options
    if body.rag_collections is not None:
        order.rag_collections = body.rag_collections
    await db.commit()
    await db.refresh(order)
    return {
        "id": order.id,
        "order_code": order.order_code,
        "analysis_context": order.analysis_context,
        "analysis_options": order.analysis_options,
        "report_options": order.report_options,
        "rag_collections": order.rag_collections,
    }


# ── Parse config.xlsx (utility) ─────────────────────────────────────────────

@router.post("/parse-config")
async def parse_config_xlsx(
    config_file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Parse a config.xlsx and return sample entries for the Sample Config UI."""
    import io

    try:
        import pandas as pd

        content = await config_file.read()
        df = pd.read_excel(io.BytesIO(content))

        required = {"File_Name", "Group"}
        if not required.issubset(df.columns):
            raise HTTPException(
                status_code=400,
                detail=f"config.xlsx must have columns: {required}. Found: {list(df.columns)}",
            )

        samples = []
        for _, row in df.iterrows():
            samples.append({
                "file_name": str(row["File_Name"]),
                "condition": str(row.get("Condition", row.get("Group", ""))),
                "group": str(row["Group"]),
                "replicate": int(row["Replicate"]) if "Replicate" in df.columns else 1,
            })

        return {"samples": samples}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse config: {str(e)}")


# ── Create / Start / Cancel ─────────────────────────────────────────────────

def _safe_json_loads(s: Optional[str], default=None):
    """Parse JSON safely; return default on empty/invalid."""
    if not s or not s.strip():
        return default
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse error: {e}")
        return default


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_order(
    project_name: str = Form(...),
    ptm_type: str = Form(...),
    species: str = Form(...),
    sample_config: str = Form("{}"),
    report_options: str = Form("{}"),
    analysis_context: Optional[str] = Form(None),
    analysis_options: Optional[str] = Form(None),
    rag_collections: Optional[str] = Form(None),
    pr_matrix: UploadFile = File(...),
    pg_matrix: UploadFile = File(...),
    config_file: Optional[UploadFile] = File(None),
    protein_list: Optional[UploadFile] = File(None),
    secondary_pr_matrix: Optional[UploadFile] = File(None),
    secondary_pg_matrix: Optional[UploadFile] = File(None),
    secondary_sample_config: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    from app.config import get_settings
    settings = get_settings()

    try:
        order_code = project_name.strip()
        _validate_order_code(order_code)

        # Must not exist in DB
        existing = await db.execute(select(Order).where(Order.order_code == order_code))
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail=f"Order '{order_code}' already exists. Choose a different name.",
            )

        # Must not exist in data/inputs or data/outputs
        input_dir = Path(settings.INPUT_DIR) / order_code
        output_dir = Path(settings.OUTPUT_DIR) / order_code
        if input_dir.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Order '{order_code}' already has data in inputs. Choose a different name.",
            )
        if output_dir.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Order '{order_code}' already has data in outputs. Choose a different name.",
            )

        order_dir = input_dir
        order_dir.mkdir(parents=True, exist_ok=True)

        async def save_upload(upload: UploadFile, subdir: str = "") -> str:
            target_dir = order_dir / subdir if subdir else order_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            file_path = target_dir / upload.filename
            content = await upload.read()
            file_path.write_bytes(content)
            return str(file_path)

        pr_path = await save_upload(pr_matrix)
        pg_path = await save_upload(pg_matrix)

        # Secondary files for Cross-Talk mode
        secondary_pr_path = None
        secondary_pg_path = None
        if secondary_pr_matrix and secondary_pr_matrix.filename:
            secondary_pr_path = await save_upload(secondary_pr_matrix, "secondary")
        if secondary_pg_matrix and secondary_pg_matrix.filename:
            secondary_pg_path = await save_upload(secondary_pg_matrix, "secondary")

        fasta_path = _resolve_fasta(settings.REFERENCE_DIR, species)
        if not fasta_path:
            raise HTTPException(
                status_code=400,
                detail=f"No reference FASTA found for species '{species}' in {settings.REFERENCE_DIR}/{species}",
            )

        # Sample config — prefer the JSON field from frontend; fall back to xlsx parsing
        sample_config_data = _safe_json_loads(sample_config, {})

        config_path = None
        if config_file and config_file.filename:
            config_path = await save_upload(config_file)
            if not sample_config_data.get("samples"):
                try:
                    import pandas as pd
                    df = pd.read_excel(config_path)
                    if "File_Name" in df.columns and "Group" in df.columns:
                        sample_config_data = {
                            "source": "xlsx",
                            "samples": [
                                {
                                    "file_name": str(row["File_Name"]),
                                    "condition": str(row.get("Condition", row.get("Group", ""))),
                                    "group": str(row["Group"]),
                                    "replicate": int(row["Replicate"]) if "Replicate" in df.columns else 1,
                                }
                                for _, row in df.iterrows()
                            ],
                        }
                except Exception as e:
                    logger.warning(f"Failed to parse config xlsx: {e}")

        # Analysis options (downsampling)
        analysis_options_data = _safe_json_loads(analysis_options)
        if protein_list and protein_list.filename:
            protein_list_path = await save_upload(protein_list)
            if analysis_options_data:
                analysis_options_data["protein_list_path"] = protein_list_path

        report_options_data = _safe_json_loads(report_options, {})
        if not report_options_data:
            raise HTTPException(status_code=400, detail="Invalid report_options JSON")

        # RAG collection selection (list of collection IDs; null = all active)
        rag_collections_data = _safe_json_loads(rag_collections)

        # Determine secondary_ptm_type from report_options or analysis_context
        secondary_ptm_type_val = None
        secondary_sample_config_data = _safe_json_loads(secondary_sample_config) if secondary_sample_config else None
        if secondary_pr_path or secondary_pg_path:
            secondary_ptm_type_val = (
                report_options_data.get("secondary_ptm_type")
                or (_safe_json_loads(analysis_context) or {}).get("secondary_ptm_type")
                or ("ubiquitylation" if ptm_type == "phosphorylation" else "phosphorylation")
            )

        order = Order(
            order_code=order_code,
            user_id=user.id if user.id != 0 else None,
            project_name=project_name,
            ptm_type=ptm_type,
            species=species,
            sample_config=sample_config_data,
            analysis_context=_safe_json_loads(analysis_context),
            analysis_options=analysis_options_data,
            report_options=report_options_data,
            rag_collections=rag_collections_data,
            pr_matrix_path=pr_path,
            pg_matrix_path=pg_path,
            fasta_path=fasta_path,
            config_xlsx_path=config_path,
            secondary_pr_matrix_path=secondary_pr_path,
            secondary_pg_matrix_path=secondary_pg_path,
            secondary_ptm_type=secondary_ptm_type_val,
            secondary_sample_config=secondary_sample_config_data,
        )

        db.add(order)
        await db.commit()
        await db.refresh(order)

        logger.info(f"Order created: {order_code} ({project_name})")

        return {
            "id": order.id,
            "order_code": order.order_code,
            "status": order.status,
            "message": "Order created successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Order create failed")
        raise HTTPException(
            status_code=500,
            detail=f"Order creation failed: {str(e)}",
        )


@router.post("/{order_id}/start")
async def start_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)
    if order.status not in ("pending", "failed", "completed", "cancelled"):
        raise HTTPException(
            status_code=400, detail=f"Cannot start order in '{order.status}' status"
        )

    # For completed or cancelled orders, clear output dir so full pipeline runs from scratch
    if order.status in ("completed", "cancelled"):
        output_dir = os.getenv("OUTPUT_DIR", "/app/data/outputs")
        order_output = Path(output_dir) / order.order_code
        if order_output.exists():
            import shutil
            try:
                shutil.rmtree(order_output)
                logger.info(f"Cleared output dir for full re-run: {order_output}")
            except OSError as e:
                logger.warning(f"Failed to clear output dir: {e}")

    order.status = "queued"
    order.current_stage = "preprocessing"
    order.progress_pct = 0
    order.started_at = datetime.utcnow()
    order.completed_at = None
    order.error_message = None
    order.run_by_user_id = user.id if getattr(user, "id", 0) != 0 else None
    await db.commit()

    condition_map = _build_condition_map(order.sample_config)

    ptm_mode = "phospho" if order.ptm_type == "phosphorylation" else "ubi"

    species_map = {"mouse": "10090", "human": "9606", "rat": "10116"}
    kegg_map = {"mouse": "mmu", "human": "hsa", "rat": "rno"}
    species_lower = (order.species or "mouse").lower()

    # Gather ChromaDB collections for RAG retrieval
    # If user selected specific collections, use only those; otherwise use all active
    selected_collection_ids = None
    if order.rag_collections and isinstance(order.rag_collections, list) and len(order.rag_collections) > 0:
        selected_collection_ids = order.rag_collections

    if selected_collection_ids:
        # User selected specific collections — resolve their chromadb_names
        coll_result = await db.execute(
            select(RagCollection.chromadb_name).where(
                RagCollection.id.in_(selected_collection_ids),
                RagCollection.is_active == True,
            )
        )
        active_collections = [r[0] for r in coll_result.fetchall()]
        logger.info(f"Order {order.order_code}: using {len(active_collections)} selected RAG collections")
    else:
        # No selection — use all active collections (backward compatible)
        coll_result = await db.execute(
            select(RagCollection.chromadb_name).where(RagCollection.is_active == True)
        )
        active_collections = [r[0] for r in coll_result.fetchall()]
        logger.info(f"Order {order.order_code}: using all {len(active_collections)} active RAG collections")

    sample_cfg = order.sample_config or {}
    report_opts = order.report_options or {}
    task_config = {
        "order_code": order.order_code,
        "pr_matrix_path": order.pr_matrix_path,
        "pg_matrix_path": order.pg_matrix_path,
        "fasta_path": order.fasta_path,
        "config_xlsx_path": order.config_xlsx_path,
        "secondary_pr_matrix_path": order.secondary_pr_matrix_path,
        "secondary_pg_matrix_path": order.secondary_pg_matrix_path,
        "ptm_mode": ptm_mode,
        "condition_map": condition_map if condition_map else None,
        "single_time_point": sample_cfg.get("single_time_point", False),
        "species_tax_id": species_map.get(species_lower, "10090"),
        "kegg_organism": kegg_map.get(species_lower, "mmu"),
        "analysis_options": order.analysis_options,
        "chromadb_collections": active_collections,
        "llm_provider": report_opts.get("llm_provider", "ollama"),
        "llm_model": report_opts.get("llm_model"),
        "rag_llm_model": report_opts.get("rag_llm_model"),
        "rag_llm_provider": report_opts.get("rag_llm_provider"),
        "report_title": report_opts.get("report_title", "PTM Comprehensive Analysis Report"),
        "research_questions": report_opts.get("research_questions", []),
        "report_type": report_opts.get("report_type", "comprehensive"),
        "report_config": report_opts.get("report_config", {}),
        "analysis_mode": report_opts.get("analysis_mode", "ptm_only"),
        "secondary_ptm_type": order.secondary_ptm_type,
        "secondary_sample_config": order.secondary_sample_config,
        "secondary_condition_map": _build_condition_map(order.secondary_sample_config) if order.secondary_sample_config else None,
    }

    from celery import Celery as CeleryClass

    celery_app = CeleryClass("ptm_workers")
    celery_app.conf.broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
    celery_app.conf.result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

    task = celery_app.send_task(
        "preprocessing.tasks.run_preprocessing",
        args=[order.id, task_config],
        queue="preprocessing",
    )

    logger.info(f"Order {order.order_code} dispatched — task_id={task.id}")

    db_log = OrderLog(
        order_id=order.id,
        stage="preprocessing",
        step="dispatch",
        status="started",
        progress_pct=0,
        message=f"Dispatched to preprocessing queue (task_id={task.id})",
    )
    db.add(db_log)
    await db.commit()

    return {
        "order_code": order.order_code,
        "status": "queued",
        "task_id": task.id,
    }


class GenerateQuestionsRequest(BaseModel):
    max_questions: int = 8
    llm_model: Optional[str] = None


@router.post("/{order_id}/generate-questions")
async def generate_questions(
    order_id: int,
    body: GenerateQuestionsRequest = GenerateQuestionsRequest(),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Generate AI research questions from the order's comprehensive MD report."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    output_dir = Path(os.getenv("OUTPUT_DIR", "/app/data/outputs")) / order.order_code

    ptm_mode = "phospho" if order.ptm_type == "phosphorylation" else "ubi"
    md_candidates = list(output_dir.glob(f"comprehensive_report_{ptm_mode}.md"))
    if not md_candidates:
        md_candidates = list(output_dir.glob("comprehensive_report_*.md"))

    if not md_candidates:
        raise HTTPException(
            status_code=400,
            detail="No comprehensive report found. Run RAG Enrichment first.",
        )

    try:
        content = md_candidates[0].read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading report: {e}")

    from celery import Celery as CeleryClass
    celery_app = CeleryClass("ptm_workers")
    celery_app.conf.broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
    celery_app.conf.result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

    llm_model = body.llm_model or (order.report_options or {}).get("llm_model") or os.getenv("LLM_MODEL", "gemma3:27b")
    llm_provider = (order.report_options or {}).get("llm_provider", "ollama")

    task = celery_app.send_task(
        "report_generation.tasks.generate_questions_task",
        args=[order_id, str(md_candidates[0]), llm_provider, llm_model, body.max_questions],
        queue="report_generation",
    )

    return {
        "task_id": task.id,
        "status": "queued",
        "md_file": md_candidates[0].name,
        "llm_model": llm_model,
    }


@router.get("/{order_id}/questions")
async def get_order_questions(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get stored research questions for an order."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    report_opts = order.report_options or {}
    return {
        "research_questions": report_opts.get("research_questions", []),
        "ai_questions": report_opts.get("ai_questions", []),
    }


class SaveQuestionsRequest(BaseModel):
    research_questions: list[str] = []
    ai_questions: list[dict] = []


@router.put("/{order_id}/questions")
async def save_order_questions(
    order_id: int,
    body: SaveQuestionsRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Save research questions for an order (used before re-running report generation)."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    report_opts = dict(order.report_options or {})
    report_opts["research_questions"] = body.research_questions
    report_opts["ai_questions"] = body.ai_questions
    order.report_options = report_opts
    await db.commit()

    return {"status": "ok", "question_count": len(body.research_questions)}


class RunStageRequest(BaseModel):
    stage: str  # "preprocessing" | "rag_enrichment" | "report_generation"


def _clear_preprocessing_outputs(order_output: Path, ptm_mode: str) -> None:
    """Remove preprocessing outputs so they can be regenerated."""
    file_suffix = "_phospho" if ptm_mode == "phospho" else "_ubi"
    patterns = [
        f"*{file_suffix}.tsv", f"*{file_suffix}.txt",
        "unified_protein_data_enriched*.tsv", "ptm_vector_data*.tsv",
        "all_protein_level_changes*.tsv", "site_level_relative*.tsv",
        "ptm_condition_comparisons*.tsv", "ptm_protein_level_changes*.tsv",
        "analysis_summary*.txt", "motif_*.tsv", "motif_*.txt",
        "normalization_factors.tsv",
    ]
    for p in patterns:
        for f in order_output.glob(p):
            try:
                f.unlink()
                logger.info(f"Cleared: {f.name}")
            except OSError as e:
                logger.warning(f"Failed to remove {f}: {e}")


@router.post("/{order_id}/run-stage")
async def run_stage(
    order_id: int,
    body: RunStageRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Re-run a specific pipeline stage without restarting from scratch."""
    VALID_STAGES = ("preprocessing", "rag_enrichment", "report_generation")
    if body.stage not in VALID_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage '{body.stage}'. Must be one of: {', '.join(VALID_STAGES)}",
        )

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    if order.status not in ("completed", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Can only re-run stages for completed or failed orders (current: '{order.status}')",
        )

    output_dir = os.getenv("OUTPUT_DIR", "/app/data/outputs")
    order_output = Path(output_dir) / order.order_code

    if not order_output.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Output directory not found for {order.order_code}. Run full analysis first.",
        )

    ptm_mode = "phospho" if order.ptm_type == "phosphorylation" else "ubi"
    file_suffix = "_phospho" if ptm_mode == "phospho" else "_ubi"

    # Gather active ChromaDB collection names
    coll_result = await db.execute(
        select(RagCollection.chromadb_name).where(RagCollection.is_active == True)
    )
    active_collections = [r[0] for r in coll_result.fetchall()]

    # Update order status
    order.status = "queued"
    order.current_stage = body.stage
    order.progress_pct = 0
    order.error_message = None
    await db.commit()

    from celery import Celery as CeleryClass
    celery_app = CeleryClass("ptm_workers")
    celery_app.conf.broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
    celery_app.conf.result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

    species_map = {"mouse": "10090", "human": "9606", "rat": "10116"}
    kegg_map = {"mouse": "mmu", "human": "hsa", "rat": "rno"}
    species_lower = (order.species or "mouse").lower()

    sample_cfg = order.sample_config or {}
    single_time_point = sample_cfg.get("single_time_point", False)

    if body.stage == "preprocessing":
        # Clear preprocessing outputs so they are regenerated
        _clear_preprocessing_outputs(order_output, ptm_mode)

        condition_map = _build_condition_map(order.sample_config)
        task_config = {
            "order_code": order.order_code,
            "pr_matrix_path": order.pr_matrix_path,
            "pg_matrix_path": order.pg_matrix_path,
            "fasta_path": order.fasta_path,
            "config_xlsx_path": order.config_xlsx_path,
            "secondary_pr_matrix_path": order.secondary_pr_matrix_path,
            "secondary_pg_matrix_path": order.secondary_pg_matrix_path,
            "ptm_mode": ptm_mode,
            "condition_map": condition_map if condition_map else None,
            "single_time_point": single_time_point,
            "species_tax_id": species_map.get(species_lower, "10090"),
            "kegg_organism": kegg_map.get(species_lower, "mmu"),
            "analysis_options": order.analysis_options,
            "experimental_context": {**(order.analysis_context or {}), "ptm_type": order.ptm_type},
            "top_n_ptms": (order.report_options or {}).get("top_n_ptms", 50),
            "chromadb_collections": active_collections,
            "llm_provider": (order.report_options or {}).get("llm_provider", "ollama"),
            "llm_model": (order.report_options or {}).get("llm_model"),
            "rag_llm_model": (order.report_options or {}).get("rag_llm_model"),
            "rag_llm_provider": (order.report_options or {}).get("rag_llm_provider"),
            "report_title": (order.report_options or {}).get("report_title", "PTM Comprehensive Analysis Report"),
            "chain_to_next": False,
        }
        task = celery_app.send_task(
            "preprocessing.tasks.run_preprocessing",
            args=[order.id, task_config],
            queue="preprocessing",
        )
        msg = f"Re-running preprocessing (task_id={task.id})"

    elif body.stage == "rag_enrichment":
        task_config = {
            "order_code": order.order_code,
            "preprocessing_output_dir": str(order_output),
            "ptm_mode": ptm_mode,
            "single_time_point": single_time_point,
            "experimental_context": {**(order.analysis_context or {}), "ptm_type": order.ptm_type},
            "chromadb_collections": active_collections,
            "llm_provider": (order.report_options or {}).get("llm_provider", "ollama"),
            "llm_model": (order.report_options or {}).get("llm_model"),
            "rag_llm_model": (order.report_options or {}).get("rag_llm_model"),
            "rag_llm_provider": (order.report_options or {}).get("rag_llm_provider"),
            "report_title": (order.report_options or {}).get("report_title", "PTM Comprehensive Analysis Report"),
            "chain_to_next": False,
        }
        task = celery_app.send_task(
            "rag_enrichment.tasks.run_rag_enrichment",
            args=[order.id, task_config],
            queue="rag_enrichment",
        )

    else:  # report_generation
        enriched_json = order_output / f"enriched_ptm_data{file_suffix}.json"
        md_report = order_output / f"comprehensive_report{file_suffix}.md"

        if not enriched_json.exists():
            order.status = "failed"
            order.error_message = "Enriched JSON not found. Run RAG Enrichment first."
            await db.commit()
            raise HTTPException(
                status_code=400,
                detail="enriched_ptm_data JSON not found. Run RAG Enrichment first.",
            )

        report_opts = order.report_options or {}
        task_config = {
            "order_code": order.order_code,
            "rag_output_dir": str(order_output),
            "enriched_json_path": str(enriched_json),
            "md_report_path": str(md_report) if md_report.exists() else None,
            "single_time_point": single_time_point,
            "experimental_context": {**(order.analysis_context or {}), "ptm_type": order.ptm_type},
            "research_questions": report_opts.get("research_questions", []),
            "chromadb_collections": active_collections,
            "llm_provider": report_opts.get("llm_provider", "ollama"),
            "llm_model": report_opts.get("llm_model"),
            "report_title": report_opts.get("report_title", "PTM Comprehensive Analysis Report"),
            "analysis_mode": report_opts.get("analysis_mode", "ptm_only"),
            "report_type": report_opts.get("report_type", "comprehensive"),
            "report_config": report_opts.get("report_config", {}),
            "secondary_ptm_type": order.secondary_ptm_type,
            "secondary_sample_config": order.secondary_sample_config,
            "secondary_condition_map": _build_condition_map(order.secondary_sample_config) if order.secondary_sample_config else None,
            # v9.12: Pass frontend kinase analysis results to report pipeline
            "kinase_analysis_data": order.kinase_analysis_data or {},
        }
        task = celery_app.send_task(
            "report_generation.tasks.run_report_generation",
            args=[order.id, task_config],
            queue="report_generation",
        )

    logger.info(f"Order {order.order_code} stage '{body.stage}' dispatched — task_id={task.id}, collections={active_collections}")

    db_log = OrderLog(
        order_id=order.id,
        stage=body.stage,
        step="dispatch",
        status="started",
        progress_pct=0,
        message=f"Re-running {body.stage} (task_id={task.id}, {len(active_collections)} RAG collections)",
    )
    db.add(db_log)
    await db.commit()

    return {
        "order_code": order.order_code,
        "status": "queued",
        "stage": body.stage,
        "task_id": task.id,
        "chromadb_collections": active_collections,
    }


@router.post("/{order_id}/cancel")
async def cancel_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    settings=Depends(get_settings),
):
    """Stop a running analysis. Sets order status to cancelled."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    running_statuses = ("queued", "running", "preprocessing", "rag_enrichment", "report_generation")
    if order.status not in running_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order in status '{order.status}'. Only running orders can be stopped.",
        )

    order.status = "cancelled"
    await db.commit()

    logger.info(f"Order {order.order_code} cancelled (stopped)")

    # Webhook: Cancelled (one of 3 events: Started, Completed, Failed/Cancelled)
    if settings.WEBHOOK_URL:
        try:
            await send_order_webhook(
                order_id=order.id,
                order_code=order.order_code,
                event="cancelled",
                webhook_url=settings.WEBHOOK_URL,
            )
            logger.info(f"Webhook sent for cancel: {order.order_code} -> {settings.WEBHOOK_URL}")
        except Exception as e:
            logger.warning(f"Webhook failed on cancel: {e}")
    else:
        logger.debug("WEBHOOK_URL not set, skipping webhook on cancel")

    return {"order_code": order.order_code, "status": "cancelled"}


@router.delete("/{order_id}")
async def delete_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete an order and its output files."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    if order.status not in ("pending", "completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete order while running (status: '{order.status}'). Cancel first.",
        )

    order_code = order.order_code

    from app.config import get_settings
    settings = get_settings()
    input_dir = Path(settings.INPUT_DIR) / order_code
    output_dir = Path(settings.OUTPUT_DIR) / order_code

    await db.delete(order)
    await db.commit()

    import shutil
    for d in (input_dir, output_dir):
        if d.exists():
            try:
                shutil.rmtree(d)
                logger.info(f"Removed directory: {d}")
            except OSError as e:
                logger.warning(f"Failed to remove {d}: {e}")

    logger.info(f"Order {order_code} deleted")
    return {"order_code": order_code, "status": "deleted"}


@router.get("/{order_id}/logs")
async def get_order_logs(
    order_id: int,
    stage: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    order_result = await db.execute(select(Order).where(Order.id == order_id))
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    query = select(OrderLog).where(OrderLog.order_id == order_id)
    if stage:
        query = query.where(OrderLog.stage == stage)
    query = query.order_by(OrderLog.created_at.asc())

    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "logs": [
            {
                "id": log.id,
                "stage": log.stage,
                "step": log.step,
                "status": log.status,
                "progress_pct": float(log.progress_pct) if log.progress_pct else None,
                "message": log.message,
                "duration_ms": log.duration_ms,
                "created_at": log.created_at.isoformat() + "Z",
            }
            for log in logs
        ]
    }


VECTOR_PLOT_PREFIXES = ("ptm_vector_report_", "ptm_vector_summary_report")


@router.get("/{order_id}/vector-plots")
async def get_vector_plots(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """List PTM vector plot PNG files (generated after preprocessing)."""
    from app.config import get_settings
    settings = get_settings()

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    output_dir = Path(settings.OUTPUT_DIR) / order.order_code
    if not output_dir.exists():
        return {"files": []}

    files = []
    for f in output_dir.glob("*.png"):
        if any(f.name.startswith(p) for p in VECTOR_PLOT_PREFIXES):
            files.append(f.name)
    files.sort()
    return {"files": files}


@router.get("/{order_id}/vector-plot-data")
async def get_vector_plot_data(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Return ptm_vector_data and Top N PTM list for time-series plot."""
    from app.config import get_settings
    settings = get_settings()

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    output_dir = Path(settings.OUTPUT_DIR) / order.order_code
    if not output_dir.exists():
        return {"vector_data": [], "top_n_ptms": []}

    file_suffix = "_phospho" if order.ptm_type == "phosphorylation" else "_ubi"

    # Load ptm_vector_data TSV
    vector_data = []
    for name in (f"ptm_vector_data_normalized{file_suffix}.tsv", f"ptm_vector_data_with_motifs{file_suffix}.tsv"):
        p = output_dir / name
        if p.exists():
            import csv
            with open(p, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    gene = row.get("Gene.Name", row.get("gene", ""))
                    pos = row.get("PTM_Position", row.get("position", ""))
                    cond = row.get("Condition", "")
                    rel_fc = row.get("PTM_Relative_Log2FC", "")
                    abs_fc = row.get("PTM_Absolute_Log2FC", "")
                    prot_fc = row.get("Protein_Log2FC", "")
                    try:
                        rel_fc = float(rel_fc) if rel_fc else 0
                    except ValueError:
                        rel_fc = 0
                    try:
                        abs_fc = float(abs_fc) if abs_fc else 0
                    except ValueError:
                        abs_fc = 0
                    try:
                        prot_fc = float(prot_fc) if prot_fc else 0
                    except ValueError:
                        prot_fc = 0
                    vector_data.append({
                        "gene": gene,
                        "position": str(pos),
                        "condition": cond,
                        "protein_log2fc": prot_fc,
                        "ptm_relative_log2fc": rel_fc,
                        "ptm_absolute_log2fc": abs_fc,
                    })
            break

    # Load Top N PTMs — prefer enriched JSON, fall back to TSV-based selection
    top_n_ptms = []
    top_n_setting = (order.report_options or {}).get("top_n_ptms", 20)
    enriched_path = output_dir / f"enriched_ptm_data{file_suffix}.json"

    if enriched_path.exists():
        import json as _json
        with open(enriched_path, "r", encoding="utf-8") as f:
            enriched = _json.load(f)
        seen = set()
        for ptm in enriched:
            gene = ptm.get("gene") or ptm.get("Gene.Name", "")
            pos = ptm.get("position") or ptm.get("PTM_Position", "")
            key = f"{gene}_{pos}"
            if key not in seen and (gene or pos):
                seen.add(key)
                top_n_ptms.append({
                    "gene": str(gene),
                    "position": str(pos),
                    "label": f"{gene} {pos}".strip() or f"{gene}{pos}",
                })
    elif vector_data:
        # Fallback: derive Top N from TSV (available right after preprocessing)
        import math
        conditions = set(r["condition"] for r in vector_data if r["condition"])
        selected_keys = set()
        for cond in conditions:
            cond_rows = sorted(
                [r for r in vector_data if r["condition"] == cond],
                key=lambda r: abs(r["ptm_relative_log2fc"]),
                reverse=True,
            )
            for r in cond_rows[:top_n_setting]:
                selected_keys.add((r["gene"], r["position"]))
        for gene, pos in sorted(selected_keys):
            top_n_ptms.append({
                "gene": gene,
                "position": pos,
                "label": f"{gene} {pos}".strip(),
            })

    # Calculate suggested N: count PTMs with |Log2FC| > 2*std in any condition
    suggested_n = None
    if vector_data:
        import math
        all_fc = [abs(r["ptm_relative_log2fc"]) for r in vector_data if r["ptm_relative_log2fc"] != 0]
        if all_fc:
            mean_fc = sum(all_fc) / len(all_fc)
            std_fc = math.sqrt(sum((x - mean_fc) ** 2 for x in all_fc) / len(all_fc)) if len(all_fc) > 1 else 0
            threshold = mean_fc + 2 * std_fc if std_fc > 0 else mean_fc * 2
            significant_keys = set()
            for r in vector_data:
                if abs(r["ptm_relative_log2fc"]) >= threshold:
                    significant_keys.add((r["gene"], r["position"]))
            suggested_n = len(significant_keys) if significant_keys else None

    return {
        "vector_data": vector_data,
        "top_n_ptms": top_n_ptms,
        "suggested_n": suggested_n,
        "top_n_setting": top_n_setting,
        "source": "enriched" if enriched_path.exists() else "preprocessing",
    }


@router.get("/{order_id}/file-details")
async def get_file_details(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Return metadata (size, modified time) for all result files."""
    from app.config import get_settings
    settings = get_settings()

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    output_dir = Path(settings.OUTPUT_DIR) / order.order_code
    if not output_dir.exists():
        return {"files": [], "output_dir": str(output_dir)}

    rf = order.result_files or {}
    all_files = rf.get("all_files", [])

    details = []
    for fname in all_files:
        fpath = output_dir / fname
        if fpath.exists() and fpath.is_file():
            stat = fpath.stat()
            details.append({
                "name": fname,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
        else:
            details.append({"name": fname, "size_bytes": 0, "modified_at": None})

    host_data_dir = os.getenv("HOST_DATA_DIR", "")
    if host_data_dir:
        host_output_dir = str(Path(host_data_dir) / "outputs" / order.order_code)
    else:
        host_output_dir = str(output_dir)

    return {
        "files": details,
        "output_dir": str(output_dir),
        "host_output_dir": host_output_dir,
        "order_code": order.order_code,
    }


@router.get("/{order_id}/files/{filename}")
async def download_order_file(
    order_id: int,
    filename: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Download a result file from an order's output directory."""
    from app.config import get_settings
    settings = get_settings()

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    output_dir = Path(settings.OUTPUT_DIR) / order.order_code
    file_path = output_dir / filename

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    # Prevent path traversal
    if not file_path.resolve().is_relative_to(output_dir.resolve()):
        raise HTTPException(status_code=403, detail="Access denied")

    media_type = "application/octet-stream"
    suffix = file_path.suffix.lower()
    image_suffixes = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}
    if suffix in image_suffixes:
        media_type = image_suffixes[suffix]
    elif suffix == ".html":
        media_type = "text/html; charset=utf-8"

    return FileResponse(
        path=str(file_path),
        filename=None if suffix in image_suffixes else filename,
        media_type=media_type,
    )


@router.get("/{order_id}/files/{filename}/preview")
async def preview_order_file(
    order_id: int,
    filename: str,
    max_lines: int = 500,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Return file content as text for in-browser preview."""
    from app.config import get_settings
    settings = get_settings()

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    output_dir = Path(settings.OUTPUT_DIR) / order.order_code
    file_path = output_dir / filename

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    if not file_path.resolve().is_relative_to(output_dir.resolve()):
        raise HTTPException(status_code=403, detail="Access denied")

    ext = file_path.suffix.lower()
    if ext not in {".md", ".txt", ".tsv", ".csv", ".json", ".log"}:
        raise HTTPException(status_code=400, detail="Preview not supported for this file type")

    stat = file_path.stat()
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                lines.append(line)
        content = "".join(lines)
        total_lines = sum(1 for _ in open(file_path, "r", encoding="utf-8", errors="replace"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")

    return {
        "filename": filename,
        "content": content,
        "total_lines": total_lines,
        "truncated": total_lines > max_lines,
        "shown_lines": min(total_lines, max_lines),
        "size_bytes": stat.st_size,
        "file_type": ext.lstrip("."),
    }


@router.delete("/{order_id}/files/{filename}")
async def delete_order_file(
    order_id: int,
    filename: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete a report file from an order's output directory. Only .md, .docx, .html allowed."""
    from app.config import get_settings
    settings = get_settings()

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    ext = Path(filename).suffix.lower()
    if ext not in {".md", ".docx", ".html"}:
        raise HTTPException(status_code=400, detail="Only report files (.md, .docx, .html) can be deleted")

    output_dir = Path(settings.OUTPUT_DIR) / order.order_code
    file_path = output_dir / filename

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    if not file_path.resolve().is_relative_to(output_dir.resolve()):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        file_path.unlink()
    except OSError as e:
        logger.warning(f"Failed to delete file {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")

    rf = dict(order.result_files or {})
    all_files = list(rf.get("all_files", []))
    report_files = list(rf.get("report_files", []))
    if filename in all_files:
        all_files.remove(filename)
    if filename in report_files:
        report_files.remove(filename)
    rf["all_files"] = all_files
    rf["report_files"] = report_files
    order.result_files = rf
    await db.commit()
    await db.refresh(order)

    return {"deleted": filename}


def _generate_statistics_from_outputs(order: Order, output_dir: Path, file_suffix: str) -> dict | None:
    """Generate pipeline statistics from existing output files (for orders preprocessed before stats feature)."""
    try:
        import pandas as pd
        from datetime import datetime

        stats = {
            "metadata": {
                "ptm_mode": "phospho" if "phospho" in file_suffix else "ubi",
                "ptm_mode_name": "Phosphorylation" if "phospho" in file_suffix else "Ubiquitylation",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            "step1_input": {},
            "step2_quantification": {},
            "step3_enrichment": {},
            "step4_biological": {},
            "final_output": {},
        }

        pr_df, pg_df = None, None
        pr_path = Path(order.pr_matrix_path) if order.pr_matrix_path else None
        pg_path = Path(order.pg_matrix_path) if order.pg_matrix_path else None
        if pr_path and pr_path.exists() and pg_path and pg_path.exists():
            pr_df = pd.read_csv(pr_path, sep="\t", low_memory=False)
            pg_df = pd.read_csv(pg_path, sep="\t", low_memory=False)
            sample_cols = [c for c in pr_df.columns if c not in (
                "Protein.Group", "Protein.Ids", "Protein.Names", "Genes",
                "First.Protein.Description", "Proteotypic", "Stripped.Sequence",
                "Modified.Sequence", "Precursor.Charge", "Precursor.Id",
            )]
            stats["step1_input"] = {
                "total_precursors": len(pr_df),
                "total_proteins_pr": int(pr_df["Protein.Group"].nunique()) if "Protein.Group" in pr_df.columns else 0,
                "total_protein_groups": len(pg_df),
                "total_samples": len(sample_cols),
            }

        ptm_vector_path = output_dir / f"ptm_vector_data_normalized{file_suffix}.tsv"
        if ptm_vector_path.exists():
            ptm_df = pd.read_csv(ptm_vector_path, sep="\t", low_memory=False)
            n_pr = len(pr_df) if pr_df is not None else 0
            n_pg = len(pg_df) if pg_df is not None else 0
            # Unique sites: PTM_Site column or derive from Protein.Group + PTM_Position
            if "PTM_Site" in ptm_df.columns:
                n_sites = int(ptm_df["PTM_Site"].nunique())
            elif "Protein.Group" in ptm_df.columns and "PTM_Position" in ptm_df.columns:
                n_sites = int(ptm_df.groupby(["Protein.Group", "PTM_Position"]).ngroups)
            else:
                n_sites = len(ptm_df)
            norm_stats = {
                "pr_precursors_before": n_pr,
                "pg_proteins_before": n_pg,
                "method": "median",
                "batch_variation_corrected": True,
            }
            norm_factors_path = output_dir / "normalization_factors.tsv"
            if norm_factors_path.exists():
                try:
                    nf_df = pd.read_csv(norm_factors_path, sep="\t")
                    if "Sample" in nf_df.columns:
                        norm_stats["samples_corrected"] = int(nf_df["Sample"].nunique())
                    if "Normalization_Factor" in nf_df.columns:
                        factors = nf_df["Normalization_Factor"].dropna()
                        if len(factors) > 0:
                            norm_stats["factor_range"] = [round(float(factors.min()), 3), round(float(factors.max()), 3)]
                except Exception:
                    pass
            stats["step2_quantification"] = {
                "normalization": norm_stats,
                "ptm_filtering": {
                    "total_precursors": n_pr,
                    "ptm_precursors": len(ptm_df),
                    "ptm_proteins": int(ptm_df["Protein.Group"].nunique()) if "Protein.Group" in ptm_df.columns else 0,
                    "ptm_sites": n_sites,
                    "ptm_ratio": round(len(ptm_df) / max(n_pr, 1) * 100, 1),
                },
                "relative_quant": {
                    "total_entries": len(ptm_df),
                    "unique_proteins": int(ptm_df["Protein.Group"].nunique()) if "Protein.Group" in ptm_df.columns else 0,
                    "unique_sites": n_sites,
                },
            }

        enriched_path = output_dir / f"unified_protein_data_enriched{file_suffix}.tsv"
        if enriched_path.exists():
            en_df = pd.read_csv(enriched_path, sep="\t", low_memory=False)
            s3 = {"total_rows": len(en_df), "unique_proteins": int(en_df["Protein.Group"].nunique()) if "Protein.Group" in en_df.columns else 0}
            if "Domains" in en_df.columns:
                s3["proteins_with_domains"] = int((en_df["Domains"].notna() & (en_df["Domains"] != "")).sum())
            if "Matched_Motifs" in en_df.columns:
                s3["sites_with_motifs"] = int((en_df["Matched_Motifs"].notna() & (en_df["Matched_Motifs"] != "")).sum())
            stats["step3_enrichment"] = s3

        bio_path = output_dir / f"unified_protein_data_enriched_bio_enriched{file_suffix}.tsv"
        if bio_path.exists():
            bio_df = pd.read_csv(bio_path, sep="\t", low_memory=False)
            s4 = {"total_rows": len(bio_df), "unique_proteins": int(bio_df["Protein.Group"].nunique()) if "Protein.Group" in bio_df.columns else 0}
            if "STRING_Interactors" in bio_df.columns:
                s4["proteins_with_string"] = int((bio_df["STRING_Interactors"].notna() & (bio_df["STRING_Interactors"] != "")).sum())
            if "KEGG_Pathways" in bio_df.columns:
                s4["proteins_with_kegg"] = int((bio_df["KEGG_Pathways"].notna() & (bio_df["KEGG_Pathways"] != "")).sum())
            stats["step4_biological"] = s4
            stats["final_output"] = {
                "total_rows": len(bio_df),
                "total_columns": len(bio_df.columns),
                "unique_proteins": int(bio_df["Protein.Group"].nunique()) if "Protein.Group" in bio_df.columns else 0,
                "conditions": int(bio_df["Condition"].nunique()) if "Condition" in bio_df.columns else 0,
            }

        if any(stats.get(k) for k in ("step1_input", "step2_quantification", "step3_enrichment", "step4_biological", "final_output")):
            return stats
    except Exception as e:
        logger.warning(f"Failed to generate statistics from outputs: {e}")
        return None


def _merge_cross_talk_stats(phospho_stats: dict, ubi_stats: dict) -> dict:
    """Merge phospho and ubi stats for cross-talk mode. Adds phospho_sites, ubi_sites to ptm_filtering."""
    has_phospho = phospho_stats and (phospho_stats.get("step2_quantification") or phospho_stats.get("step1_input"))
    has_ubi = ubi_stats and (ubi_stats.get("step2_quantification") or ubi_stats.get("step1_input"))
    base = phospho_stats if has_phospho else (ubi_stats if has_ubi else {})
    if not base:
        return {}
    merged = dict(base)
    ptm_filt = dict(merged.get("step2_quantification", {}).get("ptm_filtering", {}))
    if has_phospho:
        pf = phospho_stats.get("step2_quantification", {}).get("ptm_filtering", {})
        if pf.get("ptm_sites") is not None:
            ptm_filt["phospho_sites"] = pf["ptm_sites"]
    if has_ubi:
        uf = ubi_stats.get("step2_quantification", {}).get("ptm_filtering", {})
        if uf.get("ptm_sites") is not None:
            ptm_filt["ubi_sites"] = uf["ptm_sites"]
    if "step2_quantification" not in merged:
        merged["step2_quantification"] = {}
    merged["step2_quantification"] = dict(merged["step2_quantification"])
    merged["step2_quantification"]["ptm_filtering"] = ptm_filt
    merged["metadata"] = dict(merged.get("metadata") or {})
    merged["metadata"]["ptm_mode"] = "cross_talk"
    merged["metadata"]["ptm_mode_name"] = "Cross-Talk (Phos + Ubi)"
    return merged


@router.get("/{order_id}/statistics")
async def get_order_statistics(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Return pipeline statistics JSON collected during preprocessing."""
    import json as _json
    from app.config import get_settings
    settings = get_settings()

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    output_dir = Path(settings.OUTPUT_DIR) / order.order_code
    if not output_dir.exists():
        return {"statistics": None, "available": False}

    report_opts = order.report_options or {}
    is_cross_talk = report_opts.get("analysis_mode") == "cross_talk"

    if is_cross_talk:
        phospho_file = output_dir / "pipeline_statistics_phospho.json"
        ubi_file = output_dir / "pipeline_statistics_ubi.json"
        phospho_stats = None
        ubi_stats = None
        if phospho_file.exists():
            try:
                with open(phospho_file, "r", encoding="utf-8") as f:
                    phospho_stats = _json.load(f)
            except Exception:
                pass
        if ubi_file.exists():
            try:
                with open(ubi_file, "r", encoding="utf-8") as f:
                    ubi_stats = _json.load(f)
            except Exception:
                pass
        if phospho_stats or ubi_stats:
            stats = _merge_cross_talk_stats(phospho_stats or {}, ubi_stats or {})
            return {"statistics": stats, "available": True}
        phospho_fallback = _generate_statistics_from_outputs(order, output_dir, "_phospho")
        ubi_fallback = _generate_statistics_from_outputs(order, output_dir, "_ubi")
        if phospho_fallback or ubi_fallback:
            stats = _merge_cross_talk_stats(phospho_fallback or {}, ubi_fallback or {})
            if stats:
                return {"statistics": stats, "available": True}

    file_suffix = "_phospho" if order.ptm_type == "phosphorylation" else "_ubi"
    stats_file = output_dir / f"pipeline_statistics{file_suffix}.json"

    if stats_file.exists():
        try:
            with open(stats_file, "r", encoding="utf-8") as f:
                stats = _json.load(f)
            return {"statistics": stats, "available": True}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading statistics: {str(e)}")

    stats = _generate_statistics_from_outputs(order, output_dir, file_suffix)
    if stats:
        return {"statistics": stats, "available": True}
    return {"statistics": None, "available": False}



# ---------------------------------------------------------------------------
# Order Articles — articles used during analysis
# ---------------------------------------------------------------------------

@router.get("/{order_code}/articles")
async def get_order_articles(
    order_code: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get all PubMed articles used during a specific order's analysis.
    Extracts article data from the enriched_ptm_data JSON file.
    """
    import json as _json
    from app.config import get_settings as _get_settings

    _settings = _get_settings()

    result = await db.execute(select(Order).where(Order.order_code == order_code))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    output_dir = Path(_settings.OUTPUT_DIR) / order.order_code

    # Determine file suffix based on ptm_type
    file_suffix = "_phospho" if order.ptm_type == "phosphorylation" else "_ubi"

    # For cross-talk orders, collect articles from both modes
    suffixes_to_check = [file_suffix]
    analysis_mode = (order.analysis_options or {}).get("analysis_mode", "")
    if analysis_mode == "cross_talk":
        suffixes_to_check = ["_phospho", "_ubi"]

    seen_pmids = set()
    articles = []

    for suffix in suffixes_to_check:
        enriched_path = output_dir / f"enriched_ptm_data{suffix}.json"
        if not enriched_path.exists():
            continue

        try:
            with open(enriched_path, "r", encoding="utf-8") as f:
                enriched_ptms = _json.load(f)
        except Exception:
            continue

        for ptm in enriched_ptms:
            gene = ptm.get("Gene.Name") or ptm.get("gene", "Unknown")
            position = ptm.get("PTM_Position") or ptm.get("position", "")
            ptm_type_label = ptm.get("PTM_Type") or ptm.get("ptm_type", "")

            # Extract articles from enrichment data (rag_enrichment is the key used by RAG pipeline)
            enrichment = ptm.get("rag_enrichment", {}) or ptm.get("enrichment", {})
            ptm_articles = enrichment.get("articles", [])

            # Also check recent_findings as fallback
            if not ptm_articles:
                ptm_articles = enrichment.get("recent_findings", [])

            for article in ptm_articles:
                pmid = str(article.get("pmid", ""))
                if not pmid or pmid in seen_pmids:
                    continue
                seen_pmids.add(pmid)
                articles.append({
                    "pmid": pmid,
                    "title": article.get("title", ""),
                    "journal": article.get("journal", ""),
                    "year": article.get("year") or article.get("pub_date", ""),
                    "authors": article.get("authors", []),
                    "doi": article.get("doi", ""),
                    "relevance_score": article.get("relevance_score"),
                    "abstract": (article.get("abstract") or "")[:500],
                    # Traceability: which gene/PTM search found this article
                    "search_gene": article.get("search_gene") or gene,
                    "search_position": article.get("search_position") or position,
                    "search_ptm_type": article.get("search_ptm_type") or ptm_type_label,
                })

    # Sort by relevance score descending
    articles.sort(key=lambda a: a.get("relevance_score") or 0, reverse=True)

    return {
        "order_code": order_code,
        "project_name": order.project_name,
        "total_articles": len(articles),
        "articles": articles,
    }



# ── Kinase Enrichment (KEA3) ─────────────────────────────────────────────────
@router.post("/{order_id}/kinase-enrichment")
async def kinase_enrichment(
    order_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Call KEA3 API with a gene list and return ranked kinase enrichment results.

    Request body:
        {
            "genes": ["Nolc1", "Bnip2", "Lig1", ...],
            "module_label": "optional label for the co-wave module"
        }

    Returns ranked kinases from KEA3 Integrated--meanRank plus per-PTM
    kinase predictions from enriched_ptm_data if available.
    """
    import httpx
    import json as _json
    from app.config import get_settings

    settings = get_settings()

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    genes = body.get("genes", [])
    if not genes or not isinstance(genes, list):
        raise HTTPException(status_code=400, detail="genes list is required")

    module_label = body.get("module_label", "")

    # ── 1. KEA3 API call ──────────────────────────────────────────────────
    kea3_url = "https://maayanlab.cloud/kea3/api/enrich/"
    kea3_results = []
    kea3_libraries = {}
    kea3_error = None
    confidence_level = "high" if len(genes) >= 10 else ("medium" if len(genes) >= 3 else "low")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                kea3_url,
                json={"query_name": module_label or "co_wave_module", "gene_set": genes},
            )
            resp.raise_for_status()
            kea3_data = resp.json()

            # Extract Integrated--meanRank (primary) results
            integrated = kea3_data.get("Integrated--meanRank", [])
            for entry in integrated[:20]:  # Top 20 kinases
                kea3_results.append({
                    "kinase": entry.get("TF", ""),
                    "rank": entry.get("Rank", 0),
                    "score": entry.get("Score", 0),
                    "overlapping_genes": entry.get("Overlapping_Genes", "").split(",") if entry.get("Overlapping_Genes") else [],
                    "library": "Integrated--meanRank",
                })

            # Also collect top results from key individual libraries
            for lib_name in ["PTMsigDB", "The_Kinase_Library", "PhosDAll", "ChengKSIN"]:
                lib_data = kea3_data.get(lib_name, [])
                lib_top = []
                for entry in lib_data[:10]:
                    lib_top.append({
                        "kinase": entry.get("TF", ""),
                        "rank": entry.get("Rank", 0),
                        "score": entry.get("Score", 0),
                        "overlapping_genes": entry.get("Overlapping_Genes", "").split(",") if entry.get("Overlapping_Genes") else [],
                    })
                if lib_top:
                    kea3_libraries[lib_name] = lib_top

    except Exception as e:
        kea3_error = str(e)

    # ── 2. Per-PTM kinase predictions from enriched data ──────────────────
    per_ptm_kinases = {}
    output_dir = Path(settings.OUTPUT_DIR) / order.order_code
    file_suffix = "_phospho" if order.ptm_type == "phosphorylation" else "_ubi"
    enriched_path = output_dir / f"enriched_ptm_data{file_suffix}.json"

    if enriched_path.exists():
        try:
            with open(enriched_path, "r", encoding="utf-8") as f:
                enriched = _json.load(f)
            gene_set = set(g.upper() for g in genes)
            for ptm in enriched:
                gene = ptm.get("gene") or ptm.get("Gene.Name", "")
                if gene.upper() not in gene_set:
                    continue
                position = ptm.get("position") or ptm.get("PTM_Position", "")
                rag = ptm.get("rag_enrichment", {})

                # Extract kinase predictions
                kp = rag.get("kinase_prediction", {})
                predicted = kp.get("predicted_kinases", []) if isinstance(kp, dict) else []

                # Extract upstream regulators
                reg = rag.get("regulation", {})
                upstream = reg.get("upstream_regulators", []) if isinstance(reg, dict) else []
                ks_pairs = reg.get("kinase_substrate", []) if isinstance(reg, dict) else []

                per_ptm_kinases[f"{gene} {position}"] = {
                    "gene": gene,
                    "position": position,
                    "predicted_kinases": [
                        {
                            "kinase": k.get("kinase", ""),
                            "confidence": k.get("confidence", ""),
                            "mechanism": k.get("mechanism", ""),
                            "score": k.get("score", 0),
                        }
                        for k in (predicted if isinstance(predicted, list) else [])
                    ],
                    "upstream_regulators": upstream[:10] if isinstance(upstream, list) else [],
                    "kinase_substrate": [
                        {
                            "kinase": ks.get("kinase", ""),
                            "substrate": ks.get("substrate", ""),
                            "pmid": ks.get("pmid", ""),
                        }
                        for ks in (ks_pairs if isinstance(ks_pairs, list) else [])
                    ],
                }
        except Exception:
            pass  # Enriched data parsing failure is non-fatal

    # ── 3. Cross-validate: find kinases that appear in both KEA3 and per-PTM ──
    kea3_kinase_set = set(r["kinase"].upper() for r in kea3_results)
    per_ptm_kinase_set = set()
    for ptm_data in per_ptm_kinases.values():
        for k in ptm_data.get("predicted_kinases", []):
            per_ptm_kinase_set.add(k["kinase"].upper())
        for k in ptm_data.get("kinase_substrate", []):
            per_ptm_kinase_set.add(k["kinase"].upper())

    double_validated = sorted(kea3_kinase_set & per_ptm_kinase_set)

    return {
        "module_label": module_label,
        "gene_count": len(genes),
        "genes": genes,
        "confidence_level": confidence_level,
        "kea3_results": kea3_results,
        "kea3_libraries": kea3_libraries,
        "kea3_error": kea3_error,
        "per_ptm_kinases": per_ptm_kinases,
        "double_validated_kinases": double_validated,
    }


# ── Kinase Name Normalization ────────────────────────────────────────────────

# Canonical kinase name mapping: alias/variant → official gene symbol (HGNC)
# This resolves inconsistencies across data sources (LLM, UniProt, iPTMnet, text mining, motif DB)
# ── Kinase normalization (shared module) ─────────────────────────────────────
# Import from workers/common/kinase_utils.py for consistency.
# We keep a local copy of the alias map + functions so the API server
# doesn't need workers/ on sys.path at runtime.
_KINASE_ALIAS_MAP: dict[str, str] = {
    # CDK family
    "CDK": "CDK",  # family-level, keep as-is
    "CDK1/CDK2": "CDK1/CDK2",  # motif DB composite
    "CDK/MAPK": "CDK/MAPK",  # motif DB composite
    "CDC2": "CDK1", "CDK1": "CDK1", "CDC28": "CDK1",
    "CDK2": "CDK2",
    "CDK4": "CDK4", "CDK6": "CDK6",
    "CDK5": "CDK5", "CDK5R1": "CDK5",
    "CDK7": "CDK7", "CDK9": "CDK9",
    # CK (Casein Kinase) family
    "CK1": "CSNK1",  # family-level
    "CK1_CANONICAL": "CSNK1",
    "CSNK1A1": "CSNK1A1", "CSNK1D": "CSNK1D", "CSNK1E": "CSNK1E",
    "CK2": "CSNK2",  # family-level
    "CK2_EXTENDED": "CSNK2",
    "CKII_LIKE": "CSNK2",
    "CSNK2A1": "CSNK2A1", "CSNK2A2": "CSNK2A2", "CSNK2B": "CSNK2B",
    "CASEIN KINASE II": "CSNK2", "CASEIN KINASE 2": "CSNK2",
    "CASEIN KINASE I": "CSNK1", "CASEIN KINASE 1": "CSNK1",
    # MAPK family
    "MAPK": "MAPK",  # family-level
    "ERK1": "MAPK3", "MAPK3": "MAPK3",
    "ERK2": "MAPK1", "MAPK1": "MAPK1",
    "ERK1/ERK2": "MAPK3/MAPK1",
    "JNK": "MAPK8", "JNK1": "MAPK8", "MAPK8": "MAPK8",
    "JNK2": "MAPK9", "MAPK9": "MAPK9",
    "JNK3": "MAPK10", "MAPK10": "MAPK10",
    "P38": "MAPK14", "P38A": "MAPK14", "P38ALPHA": "MAPK14", "MAPK14": "MAPK14",
    "P38B": "MAPK11", "P38BETA": "MAPK11",
    # PKA / PKC / AKT
    "PKA": "PRKACA", "PRKACA": "PRKACA", "PRKACB": "PRKACB",
    "PKC": "PKC",  # family-level
    "PKCA": "PRKCA", "PRKCA": "PRKCA",
    "PKCB": "PRKCB", "PRKCB": "PRKCB",
    "PKCD": "PRKCD", "PRKCD": "PRKCD",
    "AKT": "AKT1", "AKT/PKB": "AKT1",
    "AKT1": "AKT1", "AKT2": "AKT2", "AKT3": "AKT3",
    "PKB": "AKT1",
    # GSK3
    "GSK3": "GSK3B", "GSK3_MINIMAL": "GSK3B",
    "GSK3A": "GSK3A", "GSK3B": "GSK3B",
    "GSK-3": "GSK3B", "GSK-3BETA": "GSK3B", "GSK-3ALPHA": "GSK3A",
    # PLK family
    "PLK1": "PLK1", "PLK1_EXTENDED": "PLK1",
    "PLK2": "PLK2", "PLK3": "PLK3", "PLK4": "PLK4",
    # Aurora family
    "AURORA": "AURKA",
    "AURORA_A/B": "AURKA/AURKB",
    "AURKA": "AURKA", "AURORA A": "AURKA", "AURORA-A": "AURKA",
    "AURKB": "AURKB", "AURORA B": "AURKB", "AURORA-B": "AURKB",
    "AURKC": "AURKC",
    # ATM/ATR/DNA-PK
    "ATM": "ATM", "ATR": "ATR", "ATM/ATR": "ATM/ATR",
    "DNA-PK": "PRKDC", "DNAPK": "PRKDC", "PRKDC": "PRKDC",
    # NEK family
    "NEK": "NEK",  # family-level
    "NEK2": "NEK2", "NEK6": "NEK6", "NEK2/NEK6": "NEK2/NEK6",
    # CAMK family
    "CAMK": "CAMK",  # family-level
    "CAMK2": "CAMK2",  # family-level
    "CAMK2A": "CAMK2A", "CAMK2B": "CAMK2B", "CAMK2D": "CAMK2D", "CAMK2G": "CAMK2G",
    "CAMKII": "CAMK2",
    # AMPK
    "AMPK": "PRKAA1", "PRKAA1": "PRKAA1", "PRKAA2": "PRKAA2",
    # mTOR
    "MTOR": "MTOR", "FRAP1": "MTOR",
    # Src family
    "SRC": "SRC", "SRC-FAMILY": "SRC",
    "SRC/FYN/YES": "SRC",
    "FYN": "FYN", "YES": "YES1", "YES1": "YES1",
    "LYN": "LYN", "LCK": "LCK", "HCK": "HCK",
    # Other tyrosine kinases
    "ABL": "ABL1", "ABL1": "ABL1", "ABL2": "ABL2",
    "JAK1": "JAK1", "JAK2": "JAK2", "JAK1/JAK2": "JAK1/JAK2",
    "JAK3": "JAK3", "TYK2": "TYK2",
    "SYK": "SYK", "ZAP70": "ZAP70", "SYK/ZAP70": "SYK/ZAP70",
    "BTK": "BTK",
    "FAK": "PTK2", "PTK2": "PTK2",
    "FLT3": "FLT3",
    # Receptor TKs
    "EGFR": "EGFR", "ERBB1": "EGFR", "HER1": "EGFR",
    "ERBB2": "ERBB2", "HER2": "ERBB2",
    "PDGFR": "PDGFRA", "PDGFRA": "PDGFRA", "PDGFRB": "PDGFRB",
    "PDGFR/FGFR": "PDGFRA",
    "FGFR": "FGFR1", "FGFR1": "FGFR1", "FGFR2": "FGFR2",
    "VEGFR": "KDR", "KDR": "KDR", "VEGFR2": "KDR",
    "INSR": "INSR", "IGF1R": "IGF1R", "INSR/IGF1R": "INSR/IGF1R",
    # Other kinases
    "RSK": "RPS6KA1", "RSK1": "RPS6KA1", "RSK2": "RPS6KA3",
    "SGK": "SGK1", "SGK1": "SGK1",
    "PIM1": "PIM1", "PIM2": "PIM2", "PIM1/PIM2": "PIM1/PIM2",
    "PKD": "PRKD1", "PRKD1": "PRKD1",
    "MARK": "MARK2", "MARK/PAR1": "MARK2",
    "CHK1": "CHEK1", "CHEK1": "CHEK1",
    "CHK2": "CHEK2", "CHEK2": "CHEK2",
    "CHK1/CHK2": "CHEK1/CHEK2",
    "PAK1": "PAK1", "PAK2": "PAK2", "PAK1/PAK2": "PAK1/PAK2",
    "DYRK1A": "DYRK1A", "DYRK1B": "DYRK1B", "DYRK1A/DYRK1B": "DYRK1A/DYRK1B",
    "CLK1": "CLK1", "CLK1-4": "CLK",
    "SRPK1": "SRPK1", "SRPK2": "SRPK2", "SRPK1/SRPK2": "SRPK1/SRPK2",
    "S6K": "RPS6KB1", "RPS6KB1": "RPS6KB1",
    "ROCK1": "ROCK1", "ROCK2": "ROCK2", "ROCK1/ROCK2": "ROCK1/ROCK2",
    "LATS1": "LATS1", "LATS2": "LATS2", "LATS1/LATS2": "LATS1/LATS2",
    "MST1": "STK4", "MST2": "STK3", "MST1/MST2": "STK4/STK3",
    "HIPK2": "HIPK2",
    "BUB1": "BUB1",
    "TBK1": "TBK1", "IKKE": "IKBKE", "TBK1/IKKE": "TBK1/IKBKE",
    "IKKA": "CHUK", "IKKB": "IKBKB", "IKKA/IKKB": "CHUK/IKBKB",
    "GRK": "GRK",  # family-level
    "MRCK": "CDC42BPA",
    # Ubiquitin E3 ligases
    "SCF_COMPLEX": "SCF", "APC/C_D-BOX": "APC/C", "APC/C_KEN-BOX": "APC/C",
    "HECT_E3": "HECT", "VHL": "VHL", "MDM2": "MDM2",
    "CHIP/STUB1": "STUB1", "NEDD4/ITCH": "NEDD4",
    "TRAF6": "TRAF6", "KEAP1/CUL3": "KEAP1",
    "BTRC/FBXW": "BTRC", "SMURF1/2": "SMURF1",
}

# Build reverse lookup: canonical → set of aliases (for family-level matching)
_KINASE_FAMILY_MEMBERS: dict[str, set[str]] = {}
for _alias, _canonical in _KINASE_ALIAS_MAP.items():
    _canonical_upper = _canonical.upper()
    if _canonical_upper not in _KINASE_FAMILY_MEMBERS:
        _KINASE_FAMILY_MEMBERS[_canonical_upper] = set()
    _KINASE_FAMILY_MEMBERS[_canonical_upper].add(_alias.upper())


def normalize_kinase_name(raw_name: str) -> tuple[str, str]:
    """Normalize a kinase name to its canonical form.

    Returns (canonical_name, display_name):
      - canonical_name: HGNC gene symbol or standardized family name (uppercase)
      - display_name: human-readable form for UI display

    Strategy:
      1. Exact match in alias map (case-insensitive)
      2. Strip common suffixes (" kinase", " family") and retry
      3. Try prefix matching for numbered isoforms (e.g., "CDK" matches "CDK1")
      4. Fallback: uppercase the raw name
    """
    if not raw_name or not raw_name.strip():
        return ("", "")

    name = raw_name.strip()
    name_upper = name.upper()

    # 1. Exact match
    if name_upper in _KINASE_ALIAS_MAP:
        canonical = _KINASE_ALIAS_MAP[name_upper]
        return (canonical.upper(), canonical)

    # 2. Strip common suffixes and retry
    import re as _re_norm
    cleaned = _re_norm.sub(r'\s*(kinase|family|protein|enzyme)\s*$', '', name_upper, flags=_re_norm.IGNORECASE).strip()
    if cleaned and cleaned != name_upper and cleaned in _KINASE_ALIAS_MAP:
        canonical = _KINASE_ALIAS_MAP[cleaned]
        return (canonical.upper(), canonical)

    # 3. Handle hyphenated/spaced variants (e.g., "CDK-1" → "CDK1")
    no_sep = _re_norm.sub(r'[-\s]+', '', name_upper)
    if no_sep != name_upper and no_sep in _KINASE_ALIAS_MAP:
        canonical = _KINASE_ALIAS_MAP[no_sep]
        return (canonical.upper(), canonical)

    # 4. Fallback: return uppercase
    return (name_upper, name)


def are_kinases_same_family(name_a: str, name_b: str) -> bool:
    """Check if two kinase names belong to the same family.

    Handles cases like:
      - 'CDK' (family) vs 'CDK1' (isoform) → True
      - 'CK2' vs 'CSNK2A1' → True (both normalize to CSNK2 family)
      - 'MAPK' vs 'ERK2' → True (ERK2 = MAPK1)
    """
    canon_a, _ = normalize_kinase_name(name_a)
    canon_b, _ = normalize_kinase_name(name_b)

    if not canon_a or not canon_b:
        return False

    # Exact match after normalization
    if canon_a == canon_b:
        return True

    # Check if one is a prefix of the other (family vs isoform)
    # e.g., "CDK" vs "CDK1", "MAPK" vs "MAPK14"
    if canon_a.startswith(canon_b) or canon_b.startswith(canon_a):
        return True

    # Check composite names (e.g., "CDK1/CDK2" contains "CDK1")
    parts_a = set(canon_a.split('/'))
    parts_b = set(canon_b.split('/'))
    if parts_a & parts_b:  # intersection
        return True

    # Check if either is contained in the other's composite
    for pa in parts_a:
        for pb in parts_b:
            if pa and pb and len(pa) >= 3 and len(pb) >= 3:
                if pa.startswith(pb) or pb.startswith(pa):
                    return True

    return False


# ── Motif-based Kinase Annotation ────────────────────────────────────────────
@router.post("/{order_id}/motif-kinase-annotation")
async def motif_kinase_annotation(
    order_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Annotate each PTM with motif-based kinase predictions and known kinase info.

    For each PTM in the request, returns:
      - motif_predicted_kinases: kinase families predicted from flanking sequence motif
      - known_kinases: kinases from enriched_ptm_data (RAG enrichment)
      - status: "known" | "motif_only" | "novel_candidate"
      - concordance: whether motif prediction agrees with known kinase info

    Request body:
        {
            "ptms": [
                {"gene": "Nolc1", "position": "S564"},
                ...
            ],
            "kea3_top_kinases": ["CK2A1", "CDK1", ...]  // optional, from KEA3 results
        }
    """
    import json as _json
    import re
    from app.config import get_settings

    settings = get_settings()

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    ptms = body.get("ptms", [])
    kea3_top_kinases = [k.upper() for k in body.get("kea3_top_kinases", [])]

    if not ptms:
        raise HTTPException(status_code=400, detail="ptms list is required")

    # ── 1. Load enriched_ptm_data for known kinase info ──────────────────
    output_dir = Path(settings.OUTPUT_DIR) / order.order_code
    file_suffix = "_phospho" if order.ptm_type == "phosphorylation" else "_ubi"
    enriched_path = output_dir / f"enriched_ptm_data{file_suffix}.json"

    import logging
    _log = logging.getLogger("motif_annotation")

    enriched_map = {}  # key: "GENE_POSITION" -> enriched data
    _log.warning(f"[ANNOTATION DEBUG] enriched_path={enriched_path}, exists={enriched_path.exists()}")
    if enriched_path.exists():
        try:
            with open(enriched_path, "r", encoding="utf-8") as f:
                enriched = _json.load(f)
            _log.warning(f"[ANNOTATION DEBUG] Loaded {len(enriched)} entries from enriched JSON")
            for ptm_entry in enriched:
                gene = ptm_entry.get("gene") or ptm_entry.get("Gene.Name", "")
                pos = ptm_entry.get("position") or ptm_entry.get("PTM_Position", "")
                key = f"{gene.upper()}_{str(pos).upper()}"
                enriched_map[key] = ptm_entry
            # Log sample keys and rag_enrichment structure
            sample_keys = list(enriched_map.keys())[:5]
            _log.warning(f"[ANNOTATION DEBUG] enriched_map sample keys: {sample_keys}")
            if enriched_map:
                sample_entry = list(enriched_map.values())[0]
                rag_sample = sample_entry.get("rag_enrichment", {})
                _log.warning(f"[ANNOTATION DEBUG] sample rag_enrichment keys: {list(rag_sample.keys()) if isinstance(rag_sample, dict) else type(rag_sample)}")
                kp_sample = rag_sample.get("kinase_prediction", "MISSING") if isinstance(rag_sample, dict) else "NOT_DICT"
                _log.warning(f"[ANNOTATION DEBUG] sample kinase_prediction type={type(kp_sample).__name__}, value={str(kp_sample)[:500]}")
                reg_sample = rag_sample.get("regulation", "MISSING") if isinstance(rag_sample, dict) else "NOT_DICT"
                _log.warning(f"[ANNOTATION DEBUG] sample regulation type={type(reg_sample).__name__}, value={str(reg_sample)[:500]}")
        except Exception as e:
            _log.warning(f"[ANNOTATION DEBUG] Failed to load enriched JSON: {e}")
    else:
        _log.warning(f"[ANNOTATION DEBUG] enriched_path does NOT exist")

    # ── 1b. iPTMnet direct API lookup for site-specific kinase info ──────
    # Query iPTMnet REST API for each unique gene to get enzyme (kinase) data
    # per phosphorylation site. This covers PSP + Signor + phospho.ELM data.
    import httpx
    import asyncio

    IPTMNET_BASE = "https://research.bioinformatics.udel.edu/iptmnet/api"
    # Determine organism code from order species
    species_lower = (order.species or "").lower()
    organism_code = (
        "10090" if "mouse" in species_lower or "mus" in species_lower
        else "9606" if "human" in species_lower or "homo" in species_lower
        else "10116" if "rat" in species_lower or "rattus" in species_lower
        else ""
    )

    iptmnet_cache: dict = {}  # gene_upper -> {"uniprot_ac": str, "sites": [{site, enzymes, ...}]}
    unique_genes = list(set(p.get("gene", "") for p in ptms if p.get("gene")))
    _log.warning(f"[ANNOTATION DEBUG] iPTMnet lookup: {len(unique_genes)} unique genes, organism={organism_code}")

    async def _iptmnet_lookup_gene(client: httpx.AsyncClient, gene: str) -> dict:
        """Search iPTMnet for a gene and fetch its substrate site data."""
        result = {"uniprot_ac": "", "sites": []}
        try:
            # Step 1: Search for the gene
            search_params = {
                "search_term": gene,
                "term_type": "All",
                "ptm_type": "Phosphorylation" if order.ptm_type == "phosphorylation" else "Ubiquitination",
                "role": "Substrate",
            }
            if organism_code:
                search_params["organism"] = organism_code

            resp = await client.get(f"{IPTMNET_BASE}/search", params=search_params)
            if resp.status_code != 200:
                return result

            search_data = resp.json()
            if not search_data or not isinstance(search_data, list):
                return result

            # Find best match (exact gene name match preferred)
            best_match = None
            for entry in search_data:
                if entry.get("gene_name", "").upper() == gene.upper():
                    best_match = entry
                    break
            if not best_match and search_data:
                best_match = search_data[0]

            if not best_match:
                return result

            uniprot_ac = best_match.get("iptm_id", "")
            result["uniprot_ac"] = uniprot_ac

            if not uniprot_ac:
                return result

            # Step 2: Get substrate sites with enzyme info
            await asyncio.sleep(0.3)  # Rate limiting
            resp2 = await client.get(f"{IPTMNET_BASE}/{uniprot_ac}/substrate")
            if resp2.status_code != 200:
                return result

            substrate_data = resp2.json()
            sites_list = substrate_data.get(uniprot_ac, [])
            if isinstance(sites_list, list):
                result["sites"] = sites_list

        except Exception as e:
            _log.warning(f"[ANNOTATION DEBUG] iPTMnet lookup failed for {gene}: {e}")
        return result

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # Process genes in batches of 5 with rate limiting
            for i in range(0, len(unique_genes), 5):
                batch = unique_genes[i:i+5]
                tasks = [_iptmnet_lookup_gene(client, g) for g in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for gene_name, res in zip(batch, results):
                    if isinstance(res, dict):
                        iptmnet_cache[gene_name.upper()] = res
                        sites_with_enz = [s for s in res.get("sites", []) if s.get("enzymes")]
                        _log.warning(f"[ANNOTATION DEBUG] iPTMnet {gene_name}: uniprot={res.get('uniprot_ac','')}, total_sites={len(res.get('sites',[]))}, sites_with_enzymes={len(sites_with_enz)}")
                if i + 5 < len(unique_genes):
                    await asyncio.sleep(0.5)  # Rate limiting between batches
    except Exception as e:
        _log.warning(f"[ANNOTATION DEBUG] iPTMnet batch lookup error: {e}")

    _log.warning(f"[ANNOTATION DEBUG] iPTMnet cache: {len(iptmnet_cache)} genes cached")

    # ── 1c. UniProt API lookup for site-specific kinase annotations ──────
    # UniProt Swiss-Prot entries contain "Modified residue" features with
    # descriptions like "Phosphoserine; by CDK1 and CDK2" — very high quality.
    UNIPROT_BASE = "https://rest.uniprot.org/uniprotkb"
    # Determine UniProt organism_id
    uniprot_organism_id = (
        "10090" if "mouse" in species_lower or "mus" in species_lower
        else "9606" if "human" in species_lower or "homo" in species_lower
        else "10116" if "rat" in species_lower or "rattus" in species_lower
        else ""
    )

    uniprot_cache: dict = {}  # gene_upper -> {pos_int -> [kinase_name, ...]}

    async def _uniprot_lookup_gene(client: httpx.AsyncClient, gene: str) -> dict:
        """Query UniProt for a gene and extract kinase annotations from Modified residue features."""
        result = {}  # pos_int -> [kinase_names]
        try:
            # First try to get the UniProt AC from iPTMnet cache (already resolved)
            iptm_data = iptmnet_cache.get(gene.upper(), {})
            uniprot_ac = iptm_data.get("uniprot_ac", "")

            if uniprot_ac:
                # Direct lookup by accession (fastest)
                resp = await client.get(
                    f"{UNIPROT_BASE}/{uniprot_ac}",
                    params={"fields": "ft_mod_res,cc_ptm", "format": "json"},
                )
            else:
                # Search by gene name + organism
                query = f"gene_exact:{gene}"
                if uniprot_organism_id:
                    query += f"+AND+organism_id:{uniprot_organism_id}"
                query += "+AND+reviewed:true"
                resp = await client.get(
                    f"{UNIPROT_BASE}/search",
                    params={"query": query, "fields": "accession,ft_mod_res,cc_ptm", "format": "json", "size": "1"},
                )

            if resp.status_code != 200:
                return result

            data = resp.json()
            # Handle search vs direct lookup
            if "results" in data:
                entries = data.get("results", [])
                entry = entries[0] if entries else {}
            else:
                entry = data

            if not entry:
                return result

            # Parse "Modified residue" features for kinase annotations
            # Example: {type: "Modified residue", location: {start: {value: 198}}, description: "Phosphothreonine; by CDK1 and CDK2"}
            import re as _re
            by_pattern = _re.compile(r'by\s+(.+)', _re.IGNORECASE)

            for feat in entry.get("features", []):
                if feat.get("type") != "Modified residue":
                    continue
                desc = feat.get("description", "")
                pos_val = feat.get("location", {}).get("start", {}).get("value")
                if not pos_val or not desc:
                    continue

                # Filter by PTM type
                desc_lower = desc.lower()
                if order.ptm_type == "phosphorylation":
                    if not any(kw in desc_lower for kw in ("phospho", "phosph")):
                        continue
                elif order.ptm_type == "ubiquitylation":
                    if "ubiquit" not in desc_lower:
                        continue

                # Extract kinase names from "by KINASE1 and KINASE2" pattern
                by_match = by_pattern.search(desc)
                if by_match:
                    kinase_str = by_match.group(1).strip()
                    # Split by " and ", ", ", "/"
                    kinase_names = _re.split(r'\s+and\s+|,\s*|/', kinase_str)
                    kinase_names = [k.strip() for k in kinase_names if k.strip() and len(k.strip()) > 1]
                    if kinase_names:
                        result[int(pos_val)] = kinase_names

            # Also parse PTM comments for additional kinase info
            # Example: "Phosphorylated at Ser-4 by PLK1 and PLK2."
            ptm_comment_pattern = _re.compile(
                r'(?:phosphorylated|ubiquitinated)\s+(?:at\s+)?(?:Ser|Thr|Tyr|Lys)-?(\d+)\s+by\s+([^.;]+)',
                _re.IGNORECASE,
            )
            for comment in entry.get("comments", []):
                if comment.get("commentType") != "PTM":
                    continue
                for text_obj in comment.get("texts", []):
                    text_val = text_obj.get("value", "")
                    for cm in ptm_comment_pattern.finditer(text_val):
                        c_pos = int(cm.group(1))
                        c_kinases_str = cm.group(2).strip()
                        c_kinases = _re.split(r'\s+and\s+|,\s*|/', c_kinases_str)
                        c_kinases = [k.strip() for k in c_kinases if k.strip() and len(k.strip()) > 1]
                        if c_kinases:
                            if c_pos in result:
                                existing = set(k.upper() for k in result[c_pos])
                                for ck in c_kinases:
                                    if ck.upper() not in existing:
                                        result[c_pos].append(ck)
                            else:
                                result[c_pos] = c_kinases

        except Exception as e:
            _log.warning(f"[ANNOTATION DEBUG] UniProt lookup failed for {gene}: {e}")
        return result

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            for i in range(0, len(unique_genes), 5):
                batch = unique_genes[i:i+5]
                tasks = [_uniprot_lookup_gene(client, g) for g in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for gene_name, res in zip(batch, results):
                    if isinstance(res, dict) and res:
                        uniprot_cache[gene_name.upper()] = res
                        _log.warning(f"[ANNOTATION DEBUG] UniProt {gene_name}: {len(res)} sites with kinase annotations")
                if i + 5 < len(unique_genes):
                    await asyncio.sleep(0.3)  # Rate limiting
    except Exception as e:
        _log.warning(f"[ANNOTATION DEBUG] UniProt batch lookup error: {e}")

    _log.warning(f"[ANNOTATION DEBUG] UniProt cache: {len(uniprot_cache)} genes cached")

    # ── 2. Load motif data from TSV (Matched_Motifs, Predicted_Regulator) ─
    motif_map = {}  # key: "GENE_POSITION" -> {"motifs": str, "regulators": str}
    for name in (
        f"ptm_vector_data_with_motifs{file_suffix}.tsv",
        f"ptm_vector_data_normalized{file_suffix}.tsv",
    ):
        p = output_dir / name
        if p.exists():
            try:
                import csv
                with open(p, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f, delimiter="\t")
                    for row in reader:
                        gene = row.get("Gene.Name", row.get("gene", ""))
                        pos = row.get("PTM_Position", row.get("position", ""))
                        key = f"{gene.upper()}_{str(pos).upper()}"
                        if key not in motif_map:
                            motif_map[key] = {
                                "matched_motifs": row.get("Matched_Motifs", ""),
                                "predicted_regulator": row.get("Predicted_Regulator", ""),
                                "sequence_window": row.get("Motifs_Sequence_Window", row.get("Sequence_Window", "")),
                            }
            except Exception:
                pass
            break

    # ── 3. Motif DB for fallback prediction (inline, matching EnhancedMotifAnalyzerV2) ─
    # ── Expanded Phosphorylation Motif DB (~50 kinase families) ──
    phospho_motif_db = {
        # === Proline-directed kinases ===
        "CDK1/CDK2": r"[ST]P.[KR]",          # CDK consensus (S/T-P-x-K/R)
        "CDK/MAPK": r"[ST]P",                 # Minimal Pro-directed
        "ERK1/ERK2": r"P.[ST]P",              # ERK preferred (P-x-S/T-P)
        "JNK": r"[ST]P",                       # JNK (Pro-directed, similar to MAPK)
        "p38": r"[ST]P",                       # p38 MAPK
        "DYRK1A/DYRK1B": r"R..[ST]P",         # DYRK (R-x-x-S/T-P)
        # === Basophilic kinases ===
        "PKA": r"[RK][RK].[ST]",               # PKA (R/K-R/K-x-S/T)
        "PKC": r"[RK].[ST][RK]",               # PKC (R/K-x-S/T-R/K)
        "AKT/PKB": r"R.R..[ST]",               # AKT (R-x-R-x-x-S/T)
        "RSK": r"[RK].[RK]..[ST]",             # RSK (R/K-x-R/K-x-x-S/T)
        "SGK": r"R.R..[ST]",                   # SGK (similar to AKT)
        "PIM1/PIM2": r"[RK].[RK].[ST]",        # PIM kinases
        "PKD": r"[LI].[RK]..[ST]",             # PKD
        "MARK/PAR1": r"[LI].[RK]..[ST]",       # MARK/PAR1
        "CAMK2": r"[RK]..[ST]..[RK]",          # CaMKII
        "CAMK": r"[ST].[RK]",                  # General CaMK
        "AMPK": r"[LMVIF].[RK]..[ST]",         # AMPK
        "CHK1/CHK2": r"[LM].[RK]..[ST]",       # Checkpoint kinases
        "PAK1/PAK2": r"[KR].[ST]",             # PAK
        # === Acidophilic kinases ===
        "CK2": r"[ST].{1,2}[ED]",              # CK2 (S/T-x-x-E/D)
        "CK2_extended": r"[ST]..E.E",          # CK2 extended (multiple acidic)
        "CK1": r"[ST]..[ST]",                  # CK1 (pS/pT priming)
        "CK1_canonical": r"[ST].[DE]",         # CK1 canonical
        "GSK3": r"[ST]...[ST]P",               # GSK3 (primed, S-x-x-x-pS-P)
        "GSK3_minimal": r"[ST].[ST]P",         # GSK3 minimal
        "GRK": r"[DE].[ST]...[DE]",            # GRK
        "PLK1": r"[DE].[ST][ILVM]",            # PLK1 (D/E-x-S/T-hydrophobic)
        "PLK1_extended": r"[DNE].{1,2}[ST][FLIVMYW]",  # PLK1 extended
        # === Mitotic/cell cycle kinases ===
        "Aurora_A/B": r"[RK].[ST][ILVM]",      # Aurora kinases
        "NEK2/NEK6": r"[LM].[ST]",             # NEK family
        "LATS1/LATS2": r"H.[RK]...[ST]",       # Hippo pathway
        "MST1/MST2": r"[MVLI]..T",             # Hippo pathway
        "BUB1": r"[ST].[DE].[DE]",             # BUB1
        # === DNA damage response ===
        "ATM/ATR": r"[ST]Q",                   # ATM/ATR (S/T-Q)
        "DNA-PK": r"[ST]Q..",                  # DNA-PK (S/T-Q-x-x)
        "HIPK2": r"[ST]Y",                     # HIPK2
        # === Tyrosine kinases (receptor) ===
        "EGFR": r"[DE].[Y]",                   # EGFR
        "PDGFR/FGFR": r"Y..[DE]",              # PDGFR/FGFR
        "INSR/IGF1R": r"Y...[YF]",             # Insulin receptor
        "VEGFR": r"Y..[ILVM]",                 # VEGFR
        # === Tyrosine kinases (non-receptor) ===
        "Src/Fyn/Yes": r"[EDAY].[YF].{1,3}[PGAS]",  # Src family
        "Src-family": r"Y.{1,2}[DE]",          # Src family minimal
        "ABL": r"[IVLA]Y..[PG]",               # ABL
        "JAK1/JAK2": r"Y..[LIV]",              # JAK family
        "SYK/ZAP70": r"Y..[LMIV]",             # SYK/ZAP70
        "BTK": r"Y..[LIVM]",                   # BTK
        "FAK": r"Y...[DEST]",                  # FAK
        "FLT3": r"Y..[LIVM]",                  # FLT3
        # === Splicing/RNA-related kinases ===
        "CLK1-4": r"[RS].[ST]",                # CLK family
        "SRPK1/SRPK2": r"[RS].[ST]",           # SRPK family
        # === AGC kinases ===
        "mTOR": r"[ST]F",                      # mTOR (S/T-F)
        "S6K": r"[RK].[RK]..[ST]",             # S6K (similar to RSK)
        "ROCK1/ROCK2": r"[RK]...[ST]",         # ROCK
        "MRCK": r"[RK]...[ST]",                # MRCK
        # === Other kinases ===
        "CKII_like": r"[ST][DE][DE]",           # CK2-like (S/T-D/E-D/E)
        "TBK1/IKKe": r"[ST]...[DE][DE]",       # TBK1/IKKe
        "IKKa/IKKb": r"DS[GLIVMF][ST]",        # IKK
    }
    # ── Expanded Ubiquitylation Motif DB ──
    ubi_motif_db = {
        "SCF_complex": r"[DE].{0,2}[ST].[DE]",
        "APC/C_D-box": r"R..L.{2,4}[ILVM]",
        "APC/C_KEN-box": r"KEN",
        "HECT_E3": r"[LP]P.Y",
        "VHL": r"LA.{1,2}[ILVM]P",
        "MDM2": r"F..W..L",
        "CHIP/STUB1": r"[ILVM].{1,2}[ILVM]",
        "NEDD4/ITCH": r"[LP]P.Y",
        "TRAF6": r"P.E..[AQEG]",
        "KEAP1/CUL3": r"[DE][ST]GE",
        "BTRC/FBXW": r"DS[GS][ILVM][ST]",
        "SMURF1/2": r"[LP]P.Y",
    }
    motif_db = phospho_motif_db if order.ptm_type == "phosphorylation" else ubi_motif_db

    # ── Residue-based kinase family prediction (fallback when no sequence) ──
    residue_kinase_families = {
        "S": ["CK2", "CK1", "CDK/MAPK", "PKA", "PKC", "AKT", "GSK3", "PLK1", "Aurora", "ATM/ATR", "AMPK", "mTOR"],
        "T": ["CDK/MAPK", "CK2", "GSK3", "PKC", "AMPK", "PLK1", "Aurora", "NEK", "MST1/2", "CAMK"],
        "Y": ["Src-family", "EGFR", "ABL", "JAK", "SYK", "FAK", "PDGFR", "VEGFR", "BTK", "FLT3"],
    }

    # ── 4. Annotate each PTM ─────────────────────────────────────────────
    annotations = []
    _debug_count = 0
    for ptm in ptms:
        gene = ptm.get("gene", "")
        position = ptm.get("position", "")
        key = f"{gene.upper()}_{str(position).upper()}"

        # Known kinases from enriched data
        known_kinases = []
        enriched_entry = enriched_map.get(key, {})
        rag = enriched_entry.get("rag_enrichment", {})
        if _debug_count < 3:
            _log.warning(f"[ANNOTATION DEBUG] PTM={gene} {position}, key={key}, enriched_entry_found={bool(enriched_entry)}, rag_found={bool(rag)}")
            if rag and isinstance(rag, dict):
                kp_val = rag.get("kinase_prediction", {})
                reg_val = rag.get("regulation", {})
                ptm_val = rag.get("ptm_validation", {})
                ft_val = rag.get("fulltext_analysis", {})
                aa_val = rag.get("abstract_analysis", {})
                si_val = rag.get("string_interactions", [])
                _log.warning(f"[ANNOTATION DEBUG]   kinase_prediction={str(kp_val)[:200]}")
                _log.warning(f"[ANNOTATION DEBUG]   regulation.upstream_regulators={reg_val.get('upstream_regulators', []) if isinstance(reg_val, dict) else 'N/A'}")
                _log.warning(f"[ANNOTATION DEBUG]   regulation.kinase_substrate={reg_val.get('kinase_substrate', []) if isinstance(reg_val, dict) else 'N/A'}")
                _log.warning(f"[ANNOTATION DEBUG]   ptm_validation type={type(ptm_val).__name__}, keys={list(ptm_val.keys()) if isinstance(ptm_val, dict) else 'N/A'}")
                if isinstance(ptm_val, dict):
                    _log.warning(f"[ANNOTATION DEBUG]   ptm_validation.iptmnet_hits={str(ptm_val.get('iptmnet_hits', []))[:300]}")
                    _log.warning(f"[ANNOTATION DEBUG]   ptm_validation.novelty={str(ptm_val.get('novelty', {}))[:300]}")
                    _log.warning(f"[ANNOTATION DEBUG]   ptm_validation.is_known={ptm_val.get('is_known', 'N/A')}")
                _log.warning(f"[ANNOTATION DEBUG]   fulltext_analysis.key_findings={str(ft_val.get('key_findings', []) if isinstance(ft_val, dict) else 'N/A')[:300]}")
                _log.warning(f"[ANNOTATION DEBUG]   abstract_analysis keys={list(aa_val.keys()) if isinstance(aa_val, dict) else 'N/A'}, value={str(aa_val)[:200]}")
                _log.warning(f"[ANNOTATION DEBUG]   string_interactions count={len(si_val) if isinstance(si_val, list) else 'N/A'}")
            _debug_count += 1
        if rag:
            # ── Source 1: kinase_prediction (LLM-based) ──
            kp = rag.get("kinase_prediction", {})
            if isinstance(kp, str):
                import ast
                try:
                    kp = ast.literal_eval(kp) if kp.startswith("{") else {}
                except Exception:
                    kp = {}
            if isinstance(kp, dict):
                for k in kp.get("predicted_kinases", []):
                    if isinstance(k, dict) and k.get("kinase"):
                        known_kinases.append({
                            "kinase": k["kinase"],
                            "confidence": k.get("confidence", ""),
                            "mechanism": k.get("mechanism", ""),
                            "source": "rag_kinase_prediction",
                        })
                    elif isinstance(k, str) and k:
                        known_kinases.append({
                            "kinase": k, "confidence": "predicted",
                            "mechanism": "", "source": "rag_kinase_prediction",
                        })

            # ── Source 2: regulation (pattern-based) ──
            reg = rag.get("regulation", {})
            if isinstance(reg, dict):
                for ks in reg.get("kinase_substrate", []):
                    if isinstance(ks, dict) and ks.get("kinase"):
                        known_kinases.append({
                            "kinase": ks["kinase"],
                            "confidence": "literature",
                            "mechanism": f"substrate: {ks.get('substrate', '')}",
                            "source": "kinase_substrate_pair",
                            "pmid": ks.get("pmid", ""),
                        })
                for ur in reg.get("upstream_regulators", []):
                    if isinstance(ur, dict) and ur.get("regulator"):
                        known_kinases.append({
                            "kinase": ur["regulator"],
                            "confidence": ur.get("confidence", "literature"),
                            "mechanism": ur.get("mechanism", ur.get("evidence", "")),
                            "source": "upstream_regulator",
                        })
                    elif isinstance(ur, str) and ur:
                        known_kinases.append({
                            "kinase": ur, "confidence": "literature",
                            "mechanism": "", "source": "upstream_regulator",
                        })

            # ── Source 3: ptm_validation → iPTMnet enzyme info ──
            ptm_val = rag.get("ptm_validation", {})
            if isinstance(ptm_val, dict):
                # Check iptmnet_hits for enzyme info
                for hit in ptm_val.get("iptmnet_hits", []):
                    if isinstance(hit, dict):
                        enz = hit.get("enzyme") or {}
                        if isinstance(enz, dict) and enz.get("name"):
                            known_kinases.append({
                                "kinase": enz["name"],
                                "confidence": "database",
                                "mechanism": f"iPTMnet enzyme (ID: {enz.get('id', '')})",
                                "source": "iPTMnet",
                            })
                # Check novelty info for enzyme
                novelty = ptm_val.get("novelty") if isinstance(ptm_val.get("novelty"), dict) else {}
                if not novelty:
                    # ptm_validation might be stored as flat dict with enzyme at top level
                    pass
                if novelty:
                    enz = novelty.get("enzyme") or {}
                    if isinstance(enz, dict) and enz.get("name"):
                        known_kinases.append({
                            "kinase": enz["name"],
                            "confidence": "database",
                            "mechanism": f"iPTMnet validated (ID: {enz.get('id', '')})",
                            "source": "iPTMnet",
                        })

            # ── Source 4: fulltext_analysis → key_findings (kinase mentions) ──
            ft = rag.get("fulltext_analysis", {})
            if isinstance(ft, dict):
                kinase_pattern = re.compile(
                    r'(?:substrate\s+of|phosphorylated\s+by|target\s+of|regulated\s+by)'
                    r'\s+([A-Z][A-Za-z0-9]{1,10}(?:\s+kinase)?)',
                    re.IGNORECASE,
                )
                for finding in ft.get("key_findings", []):
                    if isinstance(finding, str):
                        for m in kinase_pattern.finditer(finding):
                            kinase_name = m.group(1).strip()
                            if kinase_name and len(kinase_name) > 1:
                                known_kinases.append({
                                    "kinase": kinase_name,
                                    "confidence": "text_mining",
                                    "mechanism": finding[:150],
                                    "source": "fulltext_analysis",
                                })
                # Also check per-article key_findings
                for article_result in ft.get("per_article", []):
                    if isinstance(article_result, dict):
                        for finding in article_result.get("key_findings", []):
                            if isinstance(finding, str):
                                for m in kinase_pattern.finditer(finding):
                                    kinase_name = m.group(1).strip()
                                    if kinase_name and len(kinase_name) > 1:
                                        known_kinases.append({
                                            "kinase": kinase_name,
                                            "confidence": "text_mining",
                                            "mechanism": finding[:150],
                                            "source": "fulltext_analysis",
                                            "pmid": article_result.get("pmid", ""),
                                        })

            # ── Source 5: abstract_analysis (LLM-based) ──
            aa = rag.get("abstract_analysis", {})
            if isinstance(aa, dict):
                for kinase_info in aa.get("kinases", []):
                    if isinstance(kinase_info, dict) and kinase_info.get("name"):
                        known_kinases.append({
                            "kinase": kinase_info["name"],
                            "confidence": kinase_info.get("confidence", "predicted"),
                            "mechanism": kinase_info.get("evidence", ""),
                            "source": "abstract_analysis",
                        })
                    elif isinstance(kinase_info, str) and kinase_info:
                        known_kinases.append({
                            "kinase": kinase_info, "confidence": "predicted",
                            "mechanism": "", "source": "abstract_analysis",
                        })
                # Some abstract_analysis formats store kinase info differently
                for key_name in ("upstream_kinases", "predicted_kinases", "regulators"):
                    for item in aa.get(key_name, []):
                        if isinstance(item, str) and item:
                            known_kinases.append({
                                "kinase": item, "confidence": "predicted",
                                "mechanism": "", "source": "abstract_analysis",
                            })
                        elif isinstance(item, dict) and (item.get("kinase") or item.get("name")):
                            known_kinases.append({
                                "kinase": item.get("kinase") or item.get("name"),
                                "confidence": item.get("confidence", "predicted"),
                                "mechanism": item.get("evidence", item.get("mechanism", "")),
                                "source": "abstract_analysis",
                            })

            # ── Source 6: string_interactions (protein-protein interactions) ──
            # STRING DB interactions may include kinases
            string_ints = rag.get("string_interactions", [])
            if isinstance(string_ints, list):
                kinase_keywords = {"kinase", "phosphotransferase", "CK1", "CK2", "CDK", "MAPK",
                                   "PKA", "PKC", "GSK", "AKT", "mTOR", "ATM", "ATR", "PLK",
                                   "AURK", "NEK", "DYRK", "CLK", "SRPK", "CAMK", "AMPK"}
                for si in string_ints:
                    if isinstance(si, dict):
                        partner = si.get("preferredName_B") or si.get("partner") or si.get("name", "")
                        score = si.get("score", 0)
                        if partner and score >= 700:  # High confidence STRING interaction
                            partner_upper = partner.upper()
                            if any(kw.upper() in partner_upper for kw in kinase_keywords):
                                known_kinases.append({
                                    "kinase": partner,
                                    "confidence": f"STRING (score={score})",
                                    "mechanism": "protein-protein interaction",
                                    "source": "string_db",
                                })

        # ── Source 7: iPTMnet direct API (site-specific enzyme/kinase) ──
        # This provides PSP + Signor + phospho.ELM + RLIMS-P + UniProt data
        gene_upper = gene.upper()
        iptmnet_data = iptmnet_cache.get(gene_upper, {})
        if iptmnet_data.get("sites"):
            pos_upper = str(position).upper()
            for site_entry in iptmnet_data["sites"]:
                site_name = str(site_entry.get("site", "")).upper()
                # Match position (e.g., "S564" == "S564", or "T232" == "T232")
                if site_name == pos_upper:
                    ptm_type_match = site_entry.get("ptm_type", "").lower()
                    expected_type = "phosphorylation" if order.ptm_type == "phosphorylation" else "ubiquitination"
                    if expected_type in ptm_type_match.lower():
                        for enz in site_entry.get("enzymes", []):
                            if isinstance(enz, dict) and enz.get("name"):
                                enz_name = enz["name"]
                                enz_id = enz.get("id", "")
                                # Collect sources for this site
                                site_sources = [s.get("name", "") for s in site_entry.get("sources", []) if isinstance(s, dict)]
                                pmids = site_entry.get("pmids", [])
                                known_kinases.append({
                                    "kinase": enz_name,
                                    "confidence": "database",
                                    "mechanism": f"iPTMnet site-specific (UniProt: {enz_id}, Sources: {', '.join(site_sources)})",
                                    "source": "iPTMnet_direct",
                                    "pmids": pmids[:5] if pmids else [],
                                    "uniprot_ac": iptmnet_data.get("uniprot_ac", ""),
                                })
                    break  # Found matching site, no need to continue

        # ── Source 8: UniProt API (site-specific "by KINASE" annotations) ──
        # UniProt Swiss-Prot entries contain curated kinase info per residue position
        gene_upper_for_uniprot = gene.upper()
        uniprot_sites = uniprot_cache.get(gene_upper_for_uniprot, {})
        if uniprot_sites:
            # Extract numeric position from PTM position string (e.g., "S564" -> 564, "T232" -> 232)
            pos_str = str(position)
            pos_num = None
            try:
                pos_num = int(''.join(c for c in pos_str if c.isdigit()))
            except (ValueError, TypeError):
                pass
            if pos_num and pos_num in uniprot_sites:
                for kinase_name in uniprot_sites[pos_num]:
                    known_kinases.append({
                        "kinase": kinase_name,
                        "confidence": "curated",
                        "mechanism": f"UniProt Swiss-Prot annotation (pos {pos_num})",
                        "source": "UniProt",
                    })

        # ── Normalize & Deduplicate known_kinases by canonical name ──
        for kk in known_kinases:
            canonical, display = normalize_kinase_name(kk["kinase"])
            kk["canonical_name"] = canonical
            kk["display_name"] = display
            kk["original_name"] = kk["kinase"]  # preserve raw name from source

        seen_canonical = set()
        unique_known = []
        for kk in known_kinases:
            canon = kk["canonical_name"]
            if canon not in seen_canonical:
                seen_canonical.add(canon)
                unique_known.append(kk)
            else:
                # Merge source info into existing entry
                for existing in unique_known:
                    if existing["canonical_name"] == canon:
                        # Append source if different
                        if kk.get("source") and kk["source"] != existing.get("source"):
                            if "merged_sources" not in existing:
                                existing["merged_sources"] = [existing.get("source", "")]
                            existing["merged_sources"].append(kk["source"])
                        break
        known_kinases = unique_known

        # Motif-predicted kinases (also normalize family names)
        motif_predicted = []
        motif_info = motif_map.get(key, {})
        matched_motifs_str = motif_info.get("matched_motifs", "")
        predicted_regulator_str = motif_info.get("predicted_regulator", "")
        seq_window = motif_info.get("sequence_window", "")

        if matched_motifs_str and matched_motifs_str != "No motif match":
            for motif_name in matched_motifs_str.split("; "):
                motif_name = motif_name.strip()
                if motif_name:
                    kinase_family = motif_name.split("(")[0].strip().split("_")[0]
                    canonical_family, display_family = normalize_kinase_name(kinase_family)
                    motif_predicted.append({
                        "kinase_family": kinase_family,
                        "canonical_family": canonical_family,
                        "display_family": display_family,
                        "motif": motif_name,
                        "source": "motif_analysis",
                    })

        # If no TSV motifs, try inline motif matching with sequence
        if not motif_predicted:
            # Try multiple sequence sources
            effective_seq = seq_window
            if not effective_seq or effective_seq == "No sequence":
                # Fallback 1: try enriched_ptm_data for sequence info
                if enriched_entry:
                    # Check for modified_sequence or sequence_window in enriched data
                    for seq_key in ("modified_sequence", "Modified.Sequence", "sequence_window",
                                    "Sequence_Window", "flanking_sequence"):
                        val = enriched_entry.get(seq_key, "")
                        if val and isinstance(val, str) and len(val) > 3:
                            # Clean UniMod annotations
                            effective_seq = re.sub(r'\(UniMod:\d+\)', '', val).strip()
                            break
                    # Also check inside rag_enrichment
                    if (not effective_seq or effective_seq == "No sequence") and rag and isinstance(rag, dict):
                        for seq_key in ("sequence_window", "flanking_sequence"):
                            val = rag.get(seq_key, "")
                            if val and isinstance(val, str) and len(val) > 3:
                                effective_seq = val
                                break

            if effective_seq and effective_seq != "No sequence" and len(effective_seq) > 2:
                for kinase_name, pattern in motif_db.items():
                    try:
                        if re.search(pattern, effective_seq):
                            canonical_family, display_family = normalize_kinase_name(kinase_name)
                            motif_predicted.append({
                                "kinase_family": kinase_name,
                                "canonical_family": canonical_family,
                                "display_family": display_family,
                                "motif": f"{kinase_name} motif ({pattern})",
                                "source": "inline_motif_match",
                            })
                    except re.error:
                        continue

        # Fallback 2: residue-based kinase family prediction (when no sequence at all)
        if not motif_predicted and position:
            residue = str(position)[0].upper() if position else ""
            if residue in residue_kinase_families:
                for family in residue_kinase_families[residue]:
                    canonical_family, display_family = normalize_kinase_name(family)
                    motif_predicted.append({
                        "kinase_family": family,
                        "canonical_family": canonical_family,
                        "display_family": display_family,
                        "motif": f"Residue-based ({residue}-site → {family} family)",
                        "source": "residue_prediction",
                    })

        # Determine status
        has_known = len(known_kinases) > 0
        has_motif = len(motif_predicted) > 0

        if has_known:
            status = "known"
        elif has_motif:
            status = "motif_only"
        else:
            status = "novel_candidate"

        # Concordance analysis: do motif predictions agree with known kinases?
        # Uses canonical name normalization for accurate family-level matching
        # 3-state: concordant (Match) / discordant (Mismatch) / not_applicable (N/A)
        concordance = "not_applicable"
        concordance_details = []

        if has_motif:
            # Collect canonical names from motif predictions
            motif_canonical_set = set()
            for m in motif_predicted:
                canon = m.get("canonical_family", "")
                if canon:
                    # Split composite canonical names (e.g., "CDK1/CDK2")
                    for part in canon.split("/"):
                        if part and len(part) >= 2:
                            motif_canonical_set.add(part)

            # Collect canonical names from known kinases
            known_canonical_set = set()
            if has_known:
                for k in known_kinases:
                    canon = k.get("canonical_name", k["kinase"].upper())
                    for part in canon.split("/"):
                        if part and len(part) >= 2:
                            known_canonical_set.add(part)

            if known_canonical_set and motif_canonical_set:
                # Use are_kinases_same_family for robust matching
                for known_c in known_canonical_set:
                    for motif_c in motif_canonical_set:
                        if are_kinases_same_family(known_c, motif_c):
                            concordance_details.append(
                                f"Motif '{motif_c}' matches known '{known_c}'"
                            )

                if concordance_details:
                    concordance = "concordant"
                else:
                    concordance = "discordant"

        annotations.append({
            "gene": gene,
            "position": position,
            "label": f"{gene} {position}",
            "status": status,
            "known_kinases": known_kinases,
            "motif_predicted_kinases": motif_predicted,
            "sequence_window": seq_window or "",
            "concordance": concordance,
            "concordance_details": concordance_details,
        })

    # ── 5. Group-level Anchor Kinase Inference ────────────────────────────
    # Logic: within this co-wave group of PTMs,
    #   1. Collect all known kinases from any PTM → these are "Anchor Kinases"
    #   2. For each PTM without known kinase, check if its motif prediction
    #      matches any Anchor Kinase → if yes, "Inferred" as same kinase
    #   3. PTMs with no known kinase AND no motif match → "Novel Candidate"
    #
    # Multiple anchor kinases are supported (e.g., CDK1 + CK2 in same group)

    # Step 5a: Collect all anchor kinases from the group (using canonical names)
    anchor_kinases: dict = {}  # canonical_name -> {"kinase": display_name, "canonical": canonical_name, "confirmed_ptms": [labels], "sources": set()}
    for a in annotations:
        for kk in a.get("known_kinases", []):
            canonical = kk.get("canonical_name", kk["kinase"].upper())
            display = kk.get("display_name", kk["kinase"])
            if canonical not in anchor_kinases:
                anchor_kinases[canonical] = {
                    "kinase": display,
                    "canonical": canonical,
                    "confirmed_ptms": [],
                    "sources": set(),
                }
            anchor_kinases[canonical]["confirmed_ptms"].append(a["label"])
            anchor_kinases[canonical]["sources"].add(kk.get("source", "unknown"))

    # Step 5b: For each PTM without known kinase, try to infer from anchor kinases via motif match
    inferred_assignments: list = []  # [{"ptm": label, "inferred_kinase": name, "evidence": str}]
    novel_candidates: list = []  # [{"ptm": label, "motif_predictions": [...]}]

    for a in annotations:
        if a.get("known_kinases"):  # Already has known kinase, skip
            continue

        motif_preds = a.get("motif_predicted_kinases", [])
        motif_tokens = set()
        motif_families_raw = []
        for m in motif_preds:
            family = m.get("kinase_family", "")
            motif_families_raw.append(family)
            for token in family.upper().replace("/", " ").split():
                if token and len(token) >= 2:
                    motif_tokens.add(token)

        # Try to match motif predictions against anchor kinases using canonical name matching
        matched_anchors = []
        motif_canonical_names = set()
        for m in motif_preds:
            canon = m.get("canonical_family", "")
            if canon:
                for part in canon.split("/"):
                    if part:
                        motif_canonical_names.add(part)

        for anchor_canonical, anchor_info in anchor_kinases.items():
            for motif_canon in motif_canonical_names:
                if are_kinases_same_family(anchor_canonical, motif_canon):
                    matched_anchors.append({
                        "kinase": anchor_info["kinase"],
                        "canonical": anchor_canonical,
                        "matched_motif_canonical": motif_canon,
                    })
                    break

        if matched_anchors:
            for ma in matched_anchors:
                inferred_assignments.append({
                    "ptm": a["label"],
                    "gene": a["gene"],
                    "position": a["position"],
                    "inferred_kinase": ma["kinase"],
                    "inferred_canonical": ma.get("canonical", ""),
                    "evidence": f"co-wave pattern + canonical motif match ('{ma.get('matched_motif_canonical', '')}' ↔ '{ma.get('canonical', '')}' [{ma['kinase']}])",
                    "motif_predictions": motif_families_raw,
                })
        else:
            novel_candidates.append({
                "ptm": a["label"],
                "gene": a["gene"],
                "position": a["position"],
                "motif_predictions": motif_families_raw,
                "status": a["status"],
            })

    # Step 5c: Build per-kinase module summary
    kinase_modules: list = []
    for k_canonical, anchor_info in anchor_kinases.items():
        confirmed = list(set(anchor_info["confirmed_ptms"]))
        inferred = [ia["ptm"] for ia in inferred_assignments if ia.get("inferred_canonical", "") == k_canonical or are_kinases_same_family(ia.get("inferred_canonical", ""), k_canonical)]
        kinase_modules.append({
            "kinase": anchor_info["kinase"],
            "canonical": k_canonical,
            "sources": list(anchor_info["sources"]),
            "confirmed_ptms": confirmed,
            "confirmed_count": len(confirmed),
            "inferred_ptms": inferred,
            "inferred_count": len(inferred),
            "total_count": len(confirmed) + len(inferred),
        })
    # Sort by total_count descending
    kinase_modules.sort(key=lambda x: x["total_count"], reverse=True)

    group_inference = {
        "anchor_kinases": kinase_modules,
        "inferred_assignments": inferred_assignments,
        "novel_candidates": novel_candidates,
        "summary_text": "",
    }

    # Build human-readable summary
    summary_parts = []
    for km in kinase_modules:
        summary_parts.append(
            f"{km['kinase']}: {km['confirmed_count']} confirmed + {km['inferred_count']} inferred = {km['total_count']} PTMs"
        )
    if novel_candidates:
        summary_parts.append(f"{len(novel_candidates)} PTM(s) are novel candidates (no anchor kinase match)")
    group_inference["summary_text"] = "; ".join(summary_parts) if summary_parts else "No anchor kinases found in this group"

    # ── 6. Summary statistics ────────────────────────────────────────────
    status_counts = {"known": 0, "motif_only": 0, "novel_candidate": 0}
    concordance_counts = {"concordant": 0, "discordant": 0, "not_applicable": 0}
    for a in annotations:
        status_counts[a["status"]] = status_counts.get(a["status"], 0) + 1
        concordance_counts[a["concordance"]] = concordance_counts.get(a["concordance"], 0) + 1

    return {
        "order_id": order_id,
        "ptm_count": len(annotations),
        "annotations": annotations,
        "group_inference": group_inference,
        "summary": {
            "status_counts": status_counts,
            "concordance_counts": concordance_counts,
        },
    }



# ═══════════════════════════════════════════════════════════════════════════
# GLOBAL KINASE MODULE — kinase-centric grouping across all PTMs
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/{order_id}/global-kinase-modules")
async def global_kinase_modules(
    order_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Build kinase-centric modules across ALL significant PTMs.

    Unlike motif-kinase-annotation (which annotates a single co-wave group),
    this endpoint:
      1. Runs the full 8-source annotation + motif prediction on ALL provided PTMs
      2. Groups PTMs by their regulating kinase (not by timepoint)
      3. Provides cross-module overlap with co-wave modules

    Request body:
        {
            "ptms": [{"gene": "Nolc1", "position": "S564"}, ...],
            "cowave_modules": [                       // optional, for cross-analysis
                {"id": 1, "label": "Module 1 (peak: 5min)", "ptm_keys": ["NOLC1_S564", ...]},
                ...
            ]
        }

    Returns:
        {
            "kinase_modules": [
                {
                    "kinase": "CDK5",
                    "canonical": "CDK5",
                    "sources": ["iPTMnet", "Literature", ...],
                    "source_count": 3,
                    "members": [
                        {"key": "NOLC1_S564", "gene": "Nolc1", "position": "S564",
                         "membership": "confirmed", "evidence": "iPTMnet direct"},
                        {"key": "NPM1_T199", "gene": "Npm1", "position": "T199",
                         "membership": "inferred", "evidence": "CDK motif match"},
                        ...
                    ],
                    "confirmed_count": 2,
                    "inferred_count": 3,
                    "total_count": 5,
                    "cowave_overlap": [
                        {"cowave_id": 1, "cowave_label": "Module 1 (peak: 5min)", "shared_ptms": ["NOLC1_S564"]}
                    ]
                },
                ...
            ],
            "unassigned_ptms": [...],
            "annotation_details": [...],    // per-PTM annotation (same as motif-kinase-annotation)
            "summary": {...},
            "cowave_cross_analysis": {...}  // overlap statistics
        }
    """
    import json as _json
    import re
    import logging
    from app.config import get_settings

    _log = logging.getLogger("global_kinase_modules")
    settings = get_settings()

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    ptms = body.get("ptms", [])
    cowave_modules_input = body.get("cowave_modules", [])

    if not ptms:
        raise HTTPException(status_code=400, detail="ptms list is required")

    _log.info(f"[GLOBAL-KINASE] Starting global kinase module analysis: {len(ptms)} PTMs")

    # ── 1. Run full annotation (reuse motif-kinase-annotation logic) ────────
    # Call the existing annotation endpoint internally
    annotation_result = await motif_kinase_annotation(
        order_id=order_id,
        body={"ptms": ptms},
        db=db,
        user=user,
    )

    annotations = annotation_result.get("annotations", [])
    _log.info(f"[GLOBAL-KINASE] Annotation complete: {len(annotations)} PTMs annotated")

    # ── 2. Build kinase-centric modules ─────────────────────────────────────
    # Collect ALL kinases across ALL PTMs (known + motif predicted)
    kinase_members: dict = {}  # canonical → {kinase, sources, confirmed: [], inferred: []}

    for ann in annotations:
        gene = ann.get("gene", "")
        position = ann.get("position", "")
        ptm_key = f"{gene}_{position}"  # Use gene_position format to match frontend chart keys

        # Known kinases → confirmed members
        for kk in ann.get("known_kinases", []):
            canon = kk.get("canonical_name", kk.get("kinase", "").upper())
            display = kk.get("display_name", kk.get("kinase", ""))
            source = kk.get("source", "unknown")
            if not canon or len(canon) < 2:
                continue

            if canon not in kinase_members:
                kinase_members[canon] = {
                    "kinase": display,
                    "canonical": canon,
                    "sources": set(),
                    "confirmed": [],
                    "inferred": [],
                }
            kinase_members[canon]["sources"].add(source)
            if ptm_key not in [m["key"] for m in kinase_members[canon]["confirmed"]]:
                kinase_members[canon]["confirmed"].append({
                    "key": ptm_key,
                    "gene": gene,
                    "position": position,
                    "membership": "confirmed",
                    "evidence": source,
                })

    # Now assign PTMs without known kinase → inferred via motif match
    for ann in annotations:
        if ann.get("known_kinases"):
            continue  # Already assigned as confirmed

        gene = ann.get("gene", "")
        position = ann.get("position", "")
        ptm_key = f"{gene}_{position}"  # Use gene_position format to match frontend chart keys

        motif_families = set()
        for mp in ann.get("motif_predicted_kinases", []):
            cf = mp.get("canonical_family", mp.get("kinase_family", ""))
            for part in cf.split("/"):
                if part and len(part) >= 2:
                    motif_families.add(part)

        # Try to match with existing kinase modules
        matched_kinases = []
        for canon, info in kinase_members.items():
            for mf in motif_families:
                if are_kinases_same_family(canon, mf):
                    matched_kinases.append(canon)
                    break

        if matched_kinases:
            # Assign to the kinase module with most confirmed members
            best_canon = max(matched_kinases, key=lambda c: len(kinase_members[c]["confirmed"]))
            if ptm_key not in [m["key"] for m in kinase_members[best_canon]["inferred"]]:
                kinase_members[best_canon]["inferred"].append({
                    "key": ptm_key,
                    "gene": gene,
                    "position": position,
                    "membership": "inferred",
                    "evidence": f"motif match ({', '.join(motif_families)})",
                })

    # ── 3. Build unassigned list ────────────────────────────────────────────
    all_assigned_keys = set()
    for info in kinase_members.values():
        for m in info["confirmed"]:
            all_assigned_keys.add(m["key"])
        for m in info["inferred"]:
            all_assigned_keys.add(m["key"])

    unassigned = []
    for ann in annotations:
        ptm_key = f"{ann.get('gene', '')}_{ann.get('position', '')}"  # Use gene_position format
        if ptm_key not in all_assigned_keys:
            motif_fams = [mp.get("canonical_family", mp.get("kinase_family", ""))
                          for mp in ann.get("motif_predicted_kinases", [])]
            unassigned.append({
                "key": ptm_key,
                "gene": ann.get("gene", ""),
                "position": ann.get("position", ""),
                "motif_families": motif_fams,
            })

    # ── 4. Co-wave cross-analysis ───────────────────────────────────────────
    cowave_ptm_map: dict = {}  # ptm_key → [{cowave_id, cowave_label}]
    for cw in cowave_modules_input:
        cw_id = cw.get("id", 0)
        cw_label = cw.get("label", f"Module {cw_id}")
        # Accept both "ptm_keys" and "ptms" field names (frontend sends "ptms")
        ptm_key_list = cw.get("ptm_keys", []) or cw.get("ptms", [])
        for pk in ptm_key_list:
            if pk not in cowave_ptm_map:
                cowave_ptm_map[pk] = []
            cowave_ptm_map[pk].append({"cowave_id": cw_id, "cowave_label": cw_label})

    # ── 5. Format kinase modules ────────────────────────────────────────────
    kinase_module_list = []
    for canon, info in kinase_members.items():
        members = info["confirmed"] + info["inferred"]

        # Co-wave overlap
        cowave_overlap: dict = {}  # cowave_id → {label, shared_ptms}
        for m in members:
            for cw_info in cowave_ptm_map.get(m["key"], []):
                cw_id = cw_info["cowave_id"]
                if cw_id not in cowave_overlap:
                    cowave_overlap[cw_id] = {
                        "cowave_id": cw_id,
                        "cowave_label": cw_info["cowave_label"],
                        "shared_ptms": [],
                    }
                cowave_overlap[cw_id]["shared_ptms"].append(m["key"])

        kinase_module_list.append({
            "kinase": info["kinase"],
            "canonical": canon,
            "sources": sorted(info["sources"]),
            "source_count": len(info["sources"]),
            "members": members,
            "confirmed_count": len(info["confirmed"]),
            "inferred_count": len(info["inferred"]),
            "total_count": len(members),
            "cowave_overlap": list(cowave_overlap.values()),
        })

    # Sort by total_count descending
    kinase_module_list.sort(key=lambda x: x["total_count"], reverse=True)

    # ── 6. Cowave cross-analysis summary ────────────────────────────────────
    cowave_cross = {}
    if cowave_modules_input:
        # For each co-wave module, which kinase modules overlap?
        for cw in cowave_modules_input:
            cw_id = cw.get("id", 0)
            cw_label = cw.get("label", f"Module {cw_id}")
            cw_ptm_set = set(cw.get("ptm_keys", []) or cw.get("ptms", []))
            overlapping_kinases = []
            for km in kinase_module_list:
                km_ptm_set = set(m["key"] for m in km["members"])
                shared = cw_ptm_set & km_ptm_set
                if shared:
                    overlapping_kinases.append({
                        "kinase": km["kinase"],
                        "canonical": km["canonical"],
                        "shared_count": len(shared),
                        "shared_ptms": sorted(shared),
                    })
            cowave_cross[str(cw_id)] = {
                "cowave_id": cw_id,
                "cowave_label": cw_label,
                "total_ptms": len(cw_ptm_set),
                "overlapping_kinases": overlapping_kinases,
            }

    # ── 7. Summary ──────────────────────────────────────────────────────────
    status_counts = {"known": 0, "motif_only": 0, "novel_candidate": 0}
    for ann in annotations:
        status_counts[ann.get("status", "novel_candidate")] = \
            status_counts.get(ann.get("status", "novel_candidate"), 0) + 1

    summary = {
        "total_ptms": len(annotations),
        "total_kinase_modules": len(kinase_module_list),
        "total_confirmed": sum(km["confirmed_count"] for km in kinase_module_list),
        "total_inferred": sum(km["inferred_count"] for km in kinase_module_list),
        "total_unassigned": len(unassigned),
        "status_counts": status_counts,
        "top_kinases": [
            {"kinase": km["kinase"], "canonical": km["canonical"], "total": km["total_count"]}
            for km in kinase_module_list[:10]
        ],
    }

    # ── 8. Temporal Kinase Cascade ──────────────────────────────────────────
    # Build temporal cascade: for each co-wave module (peak timepoint),
    # which kinases are active? This shows kinase activation ORDER over time.
    def _parse_time_minutes(cond: str) -> float:
        """Parse condition string like '5min', '1h', '24h' to minutes."""
        m = re.match(r'([\d.]+)\s*(h|hr|hour|min|m)?', cond, re.IGNORECASE)
        if not m:
            return 0.0
        val = float(m.group(1))
        unit = (m.group(2) or 'h').lower()
        if unit.startswith('m'):
            return val  # already minutes
        return val * 60  # hours to minutes

    temporal_cascade = {"timepoints": [], "kinase_activity": [], "cascade_flow": []}

    if cowave_modules_input:
        # Build timepoint → kinases map from co-wave modules + kinase module assignments
        tp_kinase_map: dict = {}  # peak_condition → {kinases: set, ptm_count, cowave_ids}

        for cw in cowave_modules_input:
            cw_id = cw.get("id", 0)
            cw_label = cw.get("label", f"Module {cw_id}")
            cw_ptm_keys = set(cw.get("ptm_keys", []) or cw.get("ptms", []))

            # Extract peak condition from label (e.g., "Module 1 (peak: 5min)" → "5min")
            peak_match = re.search(r'peak:\s*([\w.]+)', cw_label)
            peak_cond = peak_match.group(1) if peak_match else ""
            if not peak_cond:
                continue

            if peak_cond not in tp_kinase_map:
                tp_kinase_map[peak_cond] = {
                    "kinases": {},  # canonical → {display, sources, ptms, membership_counts}
                    "ptm_count": 0,
                    "cowave_ids": [],
                    "cowave_labels": [],
                }

            tp_kinase_map[peak_cond]["cowave_ids"].append(cw_id)
            tp_kinase_map[peak_cond]["cowave_labels"].append(cw_label)
            tp_kinase_map[peak_cond]["ptm_count"] += len(cw_ptm_keys)

            # Find which kinase modules contain these PTMs
            for km in kinase_module_list:
                km_ptm_keys = set(m["key"] for m in km["members"])
                shared = cw_ptm_keys & km_ptm_keys
                if shared:
                    canon = km["canonical"]
                    if canon not in tp_kinase_map[peak_cond]["kinases"]:
                        tp_kinase_map[peak_cond]["kinases"][canon] = {
                            "kinase": km["kinase"],
                            "canonical": canon,
                            "sources": list(km["sources"]),
                            "ptm_count": len(shared),
                            "confirmed": sum(1 for m in km["members"] if m["key"] in shared and m["membership"] == "confirmed"),
                            "inferred": sum(1 for m in km["members"] if m["key"] in shared and m["membership"] == "inferred"),
                        }
                    else:
                        tp_kinase_map[peak_cond]["kinases"][canon]["ptm_count"] += len(shared)

        # Sort timepoints chronologically
        sorted_tps = sorted(tp_kinase_map.keys(), key=lambda t: _parse_time_minutes(t))

        temporal_cascade["timepoints"] = [
            {
                "condition": tp,
                "minutes": _parse_time_minutes(tp),
                "ptm_count": tp_kinase_map[tp]["ptm_count"],
                "cowave_ids": tp_kinase_map[tp]["cowave_ids"],
                "cowave_labels": tp_kinase_map[tp]["cowave_labels"],
                "kinases": sorted(
                    tp_kinase_map[tp]["kinases"].values(),
                    key=lambda k: k["ptm_count"],
                    reverse=True,
                ),
            }
            for tp in sorted_tps
        ]

        # Build kinase activity swimlane: for each kinase, which timepoints is it active?
        all_kinase_tps: dict = {}  # canonical → {kinase, timepoints: [{condition, ptm_count}]}
        for tp_data in temporal_cascade["timepoints"]:
            for k in tp_data["kinases"]:
                canon = k["canonical"]
                if canon not in all_kinase_tps:
                    all_kinase_tps[canon] = {
                        "kinase": k["kinase"],
                        "canonical": canon,
                        "sources": k["sources"],
                        "timepoints": [],
                    }
                all_kinase_tps[canon]["timepoints"].append({
                    "condition": tp_data["condition"],
                    "ptm_count": k["ptm_count"],
                    "confirmed": k.get("confirmed", 0),
                    "inferred": k.get("inferred", 0),
                })

        temporal_cascade["kinase_activity"] = sorted(
            all_kinase_tps.values(),
            key=lambda x: (
                _parse_time_minutes(x["timepoints"][0]["condition"]) if x["timepoints"] else 999,
                -len(x["timepoints"]),
            ),
        )

        # Build cascade flow: kinases shared between adjacent timepoints
        cascade_flow = []
        for i in range(len(sorted_tps) - 1):
            tp_a = sorted_tps[i]
            tp_b = sorted_tps[i + 1]
            kinases_a = set(tp_kinase_map[tp_a]["kinases"].keys())
            kinases_b = set(tp_kinase_map[tp_b]["kinases"].keys())
            shared = kinases_a & kinases_b
            new_at_b = kinases_b - kinases_a
            lost_at_b = kinases_a - kinases_b

            cascade_flow.append({
                "from": tp_a,
                "to": tp_b,
                "shared_kinases": sorted(shared),
                "new_kinases": sorted(new_at_b),
                "lost_kinases": sorted(lost_at_b),
            })

        temporal_cascade["cascade_flow"] = cascade_flow

    _log.info(
        f"[GLOBAL-KINASE] Complete: {len(kinase_module_list)} kinase modules, "
        f"{summary['total_confirmed']} confirmed, {summary['total_inferred']} inferred, "
        f"{len(unassigned)} unassigned, "
        f"{len(temporal_cascade.get('timepoints', []))} cascade timepoints"
    )

    # ── Persist kinase analysis data to DB for use in report generation ──
    try:
        from datetime import datetime as _dt
        result_obj = await db.execute(select(Order).where(Order.id == order_id))
        order_obj = result_obj.scalar_one_or_none()
        if order_obj:
            order_obj.kinase_analysis_data = {
                "kinase_modules": kinase_module_list,
                "temporal_cascade": temporal_cascade,
                "cowave_cross_analysis": cowave_cross,
                "summary": summary,
                "saved_at": _dt.utcnow().isoformat(),
            }
            await db.commit()
            _log.info(f"[GLOBAL-KINASE] Saved kinase_analysis_data to order {order_id} DB")
    except Exception as _e:
        _log.warning(f"[GLOBAL-KINASE] Failed to save kinase_analysis_data to DB: {_e}")

    return {
        "order_id": order_id,
        "kinase_modules": kinase_module_list,
        "unassigned_ptms": unassigned,
        "annotation_details": annotations,
        "summary": summary,
        "cowave_cross_analysis": cowave_cross,
        "temporal_cascade": temporal_cascade,
    }
