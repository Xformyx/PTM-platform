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

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.order import Order, OrderLog
from app.models.rag_collection import RagCollection

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
    query = select(Order).order_by(Order.created_at.desc())
    if status_filter:
        query = query.where(Order.status == status_filter)
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    orders = result.scalars().all()

    count_result = await db.execute(select(sqlfunc.count(Order.id)))
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
                "created_at": o.created_at.isoformat(),
            }
            for o in orders
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


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
        "current_stage": order.current_stage,
        "progress_pct": float(order.progress_pct),
        "stage_detail": order.stage_detail,
        "result_files": order.result_files,
        "error_message": order.error_message,
        "started_at": order.started_at.isoformat() if order.started_at else None,
        "completed_at": order.completed_at.isoformat() if order.completed_at else None,
        "created_at": order.created_at.isoformat(),
    }


class UpdateOrderOptionsRequest(BaseModel):
    analysis_context: Optional[dict] = None
    analysis_options: Optional[dict] = None
    report_options: Optional[dict] = None


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
    await db.commit()
    await db.refresh(order)
    return {
        "id": order.id,
        "order_code": order.order_code,
        "analysis_context": order.analysis_context,
        "analysis_options": order.analysis_options,
        "report_options": order.report_options,
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

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_order(
    project_name: str = Form(...),
    ptm_type: str = Form(...),
    species: str = Form(...),
    sample_config: str = Form("{}"),
    report_options: str = Form("{}"),
    analysis_context: Optional[str] = Form(None),
    analysis_options: Optional[str] = Form(None),
    pr_matrix: UploadFile = File(...),
    pg_matrix: UploadFile = File(...),
    config_file: Optional[UploadFile] = File(None),
    protein_list: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    import json
    from pathlib import Path

    from app.config import get_settings
    settings = get_settings()

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

    fasta_path = _resolve_fasta(settings.REFERENCE_DIR, species)
    if not fasta_path:
        raise HTTPException(
            status_code=400,
            detail=f"No reference FASTA found for species '{species}' in {settings.REFERENCE_DIR}/{species}",
        )

    # Sample config — prefer the JSON field from frontend; fall back to xlsx parsing
    sample_config_data = json.loads(sample_config) if sample_config and sample_config != "{}" else {}

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
    analysis_options_data = json.loads(analysis_options) if analysis_options else None
    if protein_list and protein_list.filename:
        protein_list_path = await save_upload(protein_list)
        if analysis_options_data:
            analysis_options_data["protein_list_path"] = protein_list_path

    order = Order(
        order_code=order_code,
        user_id=user.id if user.id != 0 else None,
        project_name=project_name,
        ptm_type=ptm_type,
        species=species,
        sample_config=sample_config_data,
        analysis_context=json.loads(analysis_context) if analysis_context else None,
        analysis_options=analysis_options_data,
        report_options=json.loads(report_options),
        pr_matrix_path=pr_path,
        pg_matrix_path=pg_path,
        fasta_path=fasta_path,
        config_xlsx_path=config_path,
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
    await db.commit()

    condition_map = _build_condition_map(order.sample_config)

    ptm_mode = "phospho" if order.ptm_type == "phosphorylation" else "ubi"

    species_map = {"mouse": "10090", "human": "9606", "rat": "10116"}
    kegg_map = {"mouse": "mmu", "human": "hsa", "rat": "rno"}
    species_lower = (order.species or "mouse").lower()

    # Gather active ChromaDB collections for RAG retrieval
    coll_result = await db.execute(
        select(RagCollection.chromadb_name).where(RagCollection.is_active == True)
    )
    active_collections = [r[0] for r in coll_result.fetchall()]

    task_config = {
        "order_code": order.order_code,
        "pr_matrix_path": order.pr_matrix_path,
        "pg_matrix_path": order.pg_matrix_path,
        "fasta_path": order.fasta_path,
        "config_xlsx_path": order.config_xlsx_path,
        "ptm_mode": ptm_mode,
        "condition_map": condition_map if condition_map else None,
        "species_tax_id": species_map.get(species_lower, "10090"),
        "kegg_organism": kegg_map.get(species_lower, "mmu"),
        "analysis_options": order.analysis_options,
        "chromadb_collections": active_collections,
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
            "ptm_mode": ptm_mode,
            "condition_map": condition_map if condition_map else None,
            "species_tax_id": species_map.get(species_lower, "10090"),
            "kegg_organism": kegg_map.get(species_lower, "mmu"),
            "analysis_options": order.analysis_options,
            "experimental_context": order.analysis_context,
            "top_n_ptms": (order.report_options or {}).get("top_n_ptms", 50),
            "chromadb_collections": active_collections,
            "llm_provider": (order.report_options or {}).get("llm_provider", "ollama"),
            "llm_model": (order.report_options or {}).get("llm_model"),
            "rag_llm_model": (order.report_options or {}).get("rag_llm_model"),
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
            "experimental_context": order.analysis_context,
            "chromadb_collections": active_collections,
            "llm_provider": (order.report_options or {}).get("llm_provider", "ollama"),
            "llm_model": (order.report_options or {}).get("llm_model"),
            "rag_llm_model": (order.report_options or {}).get("rag_llm_model"),
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
            "experimental_context": order.analysis_context,
            "research_questions": report_opts.get("research_questions", []),
            "chromadb_collections": active_collections,
            "llm_provider": report_opts.get("llm_provider", "ollama"),
            "llm_model": report_opts.get("llm_model"),
            "report_title": report_opts.get("report_title", "PTM Comprehensive Analysis Report"),
            "analysis_mode": report_opts.get("analysis_mode", "ptm_only"),
            "report_type": report_opts.get("report_type", "comprehensive"),
            "report_config": report_opts.get("report_config", {}),
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
):
    """Stop a running analysis. Sets order status to cancelled."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    running_statuses = ("queued", "running", "preprocessing", "rag_enrichment", "report_generation")
    if order.status not in running_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order in status '{order.status}'. Only running orders can be stopped.",
        )

    order.status = "cancelled"
    await db.commit()

    logger.info(f"Order {order.order_code} cancelled (stopped)")

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
                "created_at": log.created_at.isoformat(),
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
                    try:
                        rel_fc = float(rel_fc) if rel_fc else 0
                    except ValueError:
                        rel_fc = 0
                    try:
                        abs_fc = float(abs_fc) if abs_fc else 0
                    except ValueError:
                        abs_fc = 0
                    vector_data.append({
                        "gene": gene,
                        "position": str(pos),
                        "condition": cond,
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
    is_image = suffix in image_suffixes
    if is_image:
        media_type = image_suffixes[suffix]

    return FileResponse(
        path=str(file_path),
        filename=None if is_image else filename,
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
