import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, text, func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.webhook import send_order_webhook
from app.dependencies import get_current_user
from app.models.order import Order, OrderLog, OrderShare
from app.models.rag_collection import RagCollection
from app.models.user import User

router = APIRouter(prefix="/orders", tags=["orders"])
logger = logging.getLogger("ptm-platform.orders")

_STAGE_LOCK_KEYS = [
    "report_gen_lock:{order_id}",
]


async def _clear_order_locks(order_id: int) -> int:
    """Remove all Redis stage-execution locks for the given order."""
    r = await get_redis()
    cleared = 0
    for pattern in _STAGE_LOCK_KEYS:
        key = pattern.format(order_id=order_id)
        if await r.delete(key):
            cleared += 1
    if cleared:
        logger.info(f"Cleared {cleared} Redis lock(s) for order {order_id}")
    return cleared


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
    from sqlalchemy import or_, text as sa_text

    is_admin = getattr(user, "role", "admin") == "admin"
    uid = user.id if not is_admin else None

    # ── Step 1: lightweight query to get sorted/paginated IDs + share info
    # Select only small columns (no JSON) for sorting, to avoid sort buffer overflow.
    id_query = (
        select(
            Order.id,
            Order.created_at,
            OrderShare.access_level.label("share_access"),
        )
        .outerjoin(
            OrderShare,
            (OrderShare.order_id == Order.id) & (OrderShare.shared_with_user_id == (uid or -1)),
        )
        .order_by(Order.created_at.desc())
    )
    if not is_admin:
        id_query = id_query.where(
            or_(Order.user_id == uid, OrderShare.shared_with_user_id == uid)
        )
    if status_filter:
        id_query = id_query.where(Order.status == status_filter)

    count_result = await db.execute(
        select(sqlfunc.count()).select_from(id_query.subquery())
    )
    total = count_result.scalar()

    id_result = await db.execute(
        id_query.offset((page - 1) * page_size).limit(page_size)
    )
    id_rows = id_result.all()
    if not id_rows:
        return {"orders": [], "total": total, "page": page, "page_size": page_size}

    order_ids = [r.id for r in id_rows]
    share_map = {r.id: r.share_access for r in id_rows}

    # ── Step 2: fetch full order data + creator/runner names for those IDs only
    CreatorUser = User.__table__.alias("creator")
    RunnerUser = User.__table__.alias("runner")
    full_query = (
        select(
            Order,
            CreatorUser.c.name.label("created_by_name"),
            RunnerUser.c.name.label("run_by_name"),
        )
        .outerjoin(CreatorUser, Order.user_id == CreatorUser.c.id)
        .outerjoin(RunnerUser, Order.run_by_user_id == RunnerUser.c.id)
        .where(Order.id.in_(order_ids))
    )
    full_result = await db.execute(full_query)
    full_rows = {row.Order.id: row for row in full_result.all()}

    # Reconstruct in original sorted order
    orders_out = []
    for oid in order_ids:
        row = full_rows.get(oid)
        if not row:
            continue
        o = row.Order
        orders_out.append({
            "id": o.id,
            "order_code": o.order_code,
            "project_name": o.project_name,
            "status": o.status,
            "ptm_type": o.ptm_type,
            "species": o.species,
            "progress_pct": 100.0 if o.status == "completed" else float(o.progress_pct),
            "current_stage": o.current_stage,
            "stage_detail": o.stage_detail,
            "error_message": o.error_message,
            "started_at": o.started_at.isoformat() + "Z" if o.started_at else None,
            "created_at": o.created_at.isoformat() + "Z",
            "completed_at": o.completed_at.isoformat() + "Z" if o.completed_at else None,
            "created_by": row.created_by_name,
            "run_by": row.run_by_name,
            "is_shared": share_map[oid] is not None,
            "share_access": share_map[oid],
        })

    return {
        "orders": orders_out,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def _get_share_access(order_id: int, user_id: int, db: AsyncSession) -> Optional[str]:
    """Return the share access level for a user on an order, or None if not shared."""
    result = await db.execute(
        select(OrderShare.access_level).where(
            OrderShare.order_id == order_id,
            OrderShare.shared_with_user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    return row


async def _check_order_access_async(order, user, db: AsyncSession) -> Optional[str]:
    """Raise 403 if user has no access. Returns share_access level or None for own/admin."""
    if getattr(user, "role", "admin") == "admin":
        return None
    if order.user_id == user.id:
        return None
    share_access = await _get_share_access(order.id, user.id, db)
    if share_access is None:
        raise HTTPException(status_code=403, detail="Not authorized to access this order")
    return share_access


async def _require_write_access(order, user, db: AsyncSession) -> None:
    """Allow only owner/admin/full_access shared users to perform write operations."""
    share_access = await _check_order_access_async(order, user, db)
    if share_access == "read_only":
        raise HTTPException(status_code=403, detail="This order is shared as read-only. Write operations are not permitted.")


def _check_order_access(order, user):
    """Raise 403 if non-admin user tries to access another user's order (sync, no share check).
    NOTE: Use _check_order_access_async for endpoints that shared users should access."""
    if getattr(user, "role", "admin") != "admin" and order.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this order")


# ── Order Share endpoints ─────────────────────────────────────────────────────

class ShareOrderRequest(BaseModel):
    user_id: int
    access_level: str  # "full_access" | "read_only"


@router.get("/shareable-users")
async def get_shareable_users(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Return list of non-admin users that an order can be shared with."""
    result = await db.execute(
        select(User.id, User.name, User.email)
        .where(User.role != "admin", User.is_active == True, User.id != user.id)
        .order_by(User.name)
    )
    users = result.all()
    return [{"id": u.id, "name": u.name, "email": u.email} for u in users]


@router.get("/{order_id}/shares")
async def get_order_shares(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """List users this order is shared with (only owner or admin can view)."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    shares_result = await db.execute(
        select(OrderShare, User.name, User.email)
        .join(User, User.id == OrderShare.shared_with_user_id)
        .where(OrderShare.order_id == order_id)
        .order_by(User.name)
    )
    shares = shares_result.all()
    return [
        {
            "user_id": s.OrderShare.shared_with_user_id,
            "name": s.name,
            "email": s.email,
            "access_level": s.OrderShare.access_level,
        }
        for s in shares
    ]


@router.post("/{order_id}/share")
async def share_order(
    order_id: int,
    body: ShareOrderRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Share an order with another user (only owner or admin)."""
    if body.access_level not in ("full_access", "read_only"):
        raise HTTPException(status_code=400, detail="access_level must be 'full_access' or 'read_only'")

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    # Verify target user exists and is non-admin
    target = await db.execute(select(User).where(User.id == body.user_id))
    target_user = target.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")
    if target_user.role == "admin":
        raise HTTPException(status_code=400, detail="Cannot share with admin users")
    if target_user.id == order.user_id:
        raise HTTPException(status_code=400, detail="Cannot share with the order owner")

    # Upsert share
    existing = await db.execute(
        select(OrderShare).where(
            OrderShare.order_id == order_id,
            OrderShare.shared_with_user_id == body.user_id,
        )
    )
    share = existing.scalar_one_or_none()
    if share:
        share.access_level = body.access_level
    else:
        share = OrderShare(
            order_id=order_id,
            shared_with_user_id=body.user_id,
            access_level=body.access_level,
        )
        db.add(share)
    await db.commit()
    return {"status": "ok", "user_id": body.user_id, "access_level": body.access_level}


@router.delete("/{order_id}/share/{target_user_id}")
async def revoke_order_share(
    order_id: int,
    target_user_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Revoke a share (only owner or admin)."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _check_order_access(order, user)

    existing = await db.execute(
        select(OrderShare).where(
            OrderShare.order_id == order_id,
            OrderShare.shared_with_user_id == target_user_id,
        )
    )
    share = existing.scalar_one_or_none()
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    await db.delete(share)
    await db.commit()
    return {"status": "ok"}


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
    share_access = await _check_order_access_async(order, user, db)

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
        "progress_pct": 100.0 if order.status == "completed" else float(order.progress_pct),
        "stage_detail": order.stage_detail,
        "result_files": order.result_files,
        "error_message": order.error_message,
        "cross_talk_data": order.cross_talk_data,
        "signal_propagation_data": order.signal_propagation_data,
        "receptor_inference_data": order.receptor_inference_data,
        "is_shared": share_access is not None,
        "share_access": share_access,
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
    await _require_write_access(order, user, db)
    if order.status not in ("registered", "completed", "failed", "cancelled"):
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


class DuplicateOrderRequest(BaseModel):
    new_order_name: str
    report_options: Optional[dict] = None
    analysis_options: Optional[dict] = None
    analysis_context: Optional[dict] = None
    rag_collections: Optional[list] = None


@router.post("/{order_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_order(
    order_id: int,
    body: DuplicateOrderRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Duplicate an existing order: copy input files and settings under a new name."""
    from app.config import get_settings
    import shutil

    settings = get_settings()

    result = await db.execute(select(Order).where(Order.id == order_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source order not found")

    new_code = body.new_order_name.strip()
    _validate_order_code(new_code)

    existing = await db.execute(select(Order).where(Order.order_code == new_code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Order '{new_code}' already exists.")

    new_input_dir = Path(settings.INPUT_DIR) / new_code
    if new_input_dir.exists():
        raise HTTPException(status_code=400, detail=f"Input directory for '{new_code}' already exists.")

    try:
        src_input_dir = Path(settings.INPUT_DIR) / source.order_code
        if src_input_dir.is_dir():
            shutil.copytree(str(src_input_dir), str(new_input_dir))
        else:
            new_input_dir.mkdir(parents=True, exist_ok=True)

        def _remap_path(original: str | None) -> str | None:
            if not original:
                return None
            p = Path(original)
            if source.order_code in p.parts:
                idx = p.parts.index(source.order_code)
                return str(Path(*p.parts[:idx], new_code, *p.parts[idx + 1 :]))
            return original

        report_opts = body.report_options if body.report_options is not None else (source.report_options or {})
        analysis_opts = body.analysis_options if body.analysis_options is not None else source.analysis_options
        analysis_ctx = body.analysis_context if body.analysis_context is not None else source.analysis_context
        rag_cols = body.rag_collections if body.rag_collections is not None else source.rag_collections

        new_order = Order(
            order_code=new_code,
            user_id=user.id if user.id != 0 else None,
            project_name=new_code,
            ptm_type=source.ptm_type,
            species=source.species,
            organism_code=source.organism_code,
            sample_config=source.sample_config,
            analysis_context=analysis_ctx,
            analysis_options=analysis_opts,
            report_options=report_opts,
            rag_collections=rag_cols,
            pr_matrix_path=_remap_path(source.pr_matrix_path),
            pg_matrix_path=_remap_path(source.pg_matrix_path),
            fasta_path=source.fasta_path,
            config_xlsx_path=_remap_path(source.config_xlsx_path),
            secondary_pr_matrix_path=_remap_path(source.secondary_pr_matrix_path),
            secondary_pg_matrix_path=_remap_path(source.secondary_pg_matrix_path),
            secondary_ptm_type=source.secondary_ptm_type,
            secondary_sample_config=source.secondary_sample_config,
        )

        db.add(new_order)
        await db.commit()
        await db.refresh(new_order)

        logger.info(f"Order duplicated: {source.order_code} → {new_code} (id={new_order.id})")

        return {
            "id": new_order.id,
            "order_code": new_order.order_code,
            "status": new_order.status,
            "message": f"Order duplicated from '{source.order_code}'",
        }
    except HTTPException:
        raise
    except Exception as e:
        if new_input_dir.exists():
            shutil.rmtree(str(new_input_dir), ignore_errors=True)
        logger.exception("Order duplicate failed")
        raise HTTPException(status_code=500, detail=f"Order duplication failed: {str(e)}")


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
    await _require_write_access(order, user, db)
    if order.status not in ("registered", "failed", "completed", "cancelled"):
        raise HTTPException(
            status_code=400, detail=f"Cannot start order in '{order.status}' status"
        )

    await _clear_order_locks(order_id)

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

    # Truncate previous run logs + webhook idempotency records
    await db.execute(
        OrderLog.__table__.delete().where(OrderLog.order_id == order.id)
    )
    try:
        await db.execute(text("DELETE FROM webhook_sent_log WHERE order_id = :oid"), {"oid": order.id})
    except Exception:
        pass

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
        "rag_enrichment_llm_model": report_opts.get("rag_enrichment_llm_model"),
        "rag_enrichment_llm_provider": report_opts.get("rag_enrichment_llm_provider"),
        "rag_llm_model": report_opts.get("rag_llm_model"),
        "rag_llm_provider": report_opts.get("rag_llm_provider"),
        "report_title": report_opts.get("report_title", "PTM Comprehensive Analysis Report"),
        "research_questions": report_opts.get("research_questions", []),
        "report_type": report_opts.get("report_type", "comprehensive"),
        "report_config": report_opts.get("report_config", {}),
        "analysis_mode": report_opts.get("analysis_mode", "ptm_only"),
        "top_n_ptms": report_opts.get("top_n_ptms", 50),
        "ptm_selection_mode": report_opts.get("ptm_selection_mode", "top_n"),
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
    await _check_order_access_async(order, user, db)

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
    await _check_order_access_async(order, user, db)

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
    await _require_write_access(order, user, db)

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
    await _require_write_access(order, user, db)

    if order.status not in ("completed", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Can only re-run stages for completed or failed orders (current: '{order.status}')",
        )

    await _clear_order_locks(order_id)

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

    # Truncate logs + webhook records for stages that will be re-run
    stage_order = ["preprocessing", "rag_enrichment", "report_generation"]
    step_map = {"preprocessing": "preprocessing", "rag_enrichment": "rag_enrichment", "report_generation": "report_generation"}
    idx = stage_order.index(body.stage)
    stages_to_clear = stage_order[idx:]
    await db.execute(
        OrderLog.__table__.delete().where(
            OrderLog.order_id == order.id,
            OrderLog.stage.in_(stages_to_clear),
        )
    )
    try:
        steps_to_clear = [step_map[s] for s in stages_to_clear] + ["order"]
        await db.execute(
            text("DELETE FROM webhook_sent_log WHERE order_id = :oid AND step IN :steps"),
            {"oid": order.id, "steps": tuple(steps_to_clear)},
        )
    except Exception:
        pass

    order.status = "queued"
    order.current_stage = body.stage
    order.progress_pct = 0
    order.error_message = None

    # v9.44: Invalidate kinase analysis cache when re-running from preprocessing
    if body.stage == "preprocessing":
        order.kinase_analysis_data = None
        order.receptor_inference_data = None
        order.signal_propagation_data = None

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
            "ptm_selection_mode": (order.report_options or {}).get("ptm_selection_mode", "top_n"),
            "chromadb_collections": active_collections,
            "llm_provider": (order.report_options or {}).get("llm_provider", "ollama"),
            "llm_model": (order.report_options or {}).get("llm_model"),
            "rag_enrichment_llm_model": (order.report_options or {}).get("rag_enrichment_llm_model"),
            "rag_enrichment_llm_provider": (order.report_options or {}).get("rag_enrichment_llm_provider"),
            "rag_llm_model": (order.report_options or {}).get("rag_llm_model"),
            "rag_llm_provider": (order.report_options or {}).get("rag_llm_provider"),
            "report_title": (order.report_options or {}).get("report_title", "PTM Comprehensive Analysis Report"),
            "chain_to_next": True,
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
            "top_n_ptms": (order.report_options or {}).get("top_n_ptms", 50),
            "ptm_selection_mode": (order.report_options or {}).get("ptm_selection_mode", "top_n"),
            "chromadb_collections": active_collections,
            "llm_provider": (order.report_options or {}).get("llm_provider", "ollama"),
            "llm_model": (order.report_options or {}).get("llm_model"),
            "rag_enrichment_llm_model": (order.report_options or {}).get("rag_enrichment_llm_model"),
            "rag_enrichment_llm_provider": (order.report_options or {}).get("rag_enrichment_llm_provider"),
            "rag_llm_model": (order.report_options or {}).get("rag_llm_model"),
            "rag_llm_provider": (order.report_options or {}).get("rag_llm_provider"),
            "report_title": (order.report_options or {}).get("report_title", "PTM Comprehensive Analysis Report"),
            "chain_to_next": True,
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
            # Fallback: any enriched_ptm_data*.json (newest first), e.g. suffix mismatch or manual copy
            _cand = sorted(
                order_output.glob("enriched_ptm_data*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if _cand:
                enriched_json = _cand[0]

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
            # v9.33: Pass PTM selection settings so kinase module analysis matches frontend
            "top_n_ptms": (order.report_options or {}).get("top_n_ptms", 50),
            "ptm_selection_mode": (order.report_options or {}).get("ptm_selection_mode", "top_n"),
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
    await _require_write_access(order, user, db)

    running_statuses = ("queued", "running", "preprocessing", "rag_enrichment", "report_generation")
    if order.status not in running_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order in status '{order.status}'. Only running orders can be stopped.",
        )

    order.status = "cancelled"
    await db.commit()

    await _clear_order_locks(order_id)

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
    await _require_write_access(order, user, db)

    if order.status not in ("registered", "completed", "failed", "cancelled"):
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


@router.get("/{order_id}/status")
async def get_order_status(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Lightweight polling endpoint — returns only status-relevant fields."""
    result = await db.execute(
        select(
            Order.id, Order.status, Order.current_stage, Order.progress_pct,
            Order.stage_detail, Order.error_message,
        ).where(Order.id == order_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    status = row[1]
    current_stage = row[2]

    # Defensive: auto-correct status if current_stage is ahead
    pipeline_stages = {"preprocessing", "rag_enrichment", "report_generation"}
    if current_stage in pipeline_stages and status in pipeline_stages and status != current_stage:
        status = current_stage
        await db.execute(
            text("UPDATE orders SET status = :s WHERE id = :oid"),
            {"s": current_stage, "oid": order_id},
        )
        await db.commit()

    return {
        "id": row[0],
        "status": status,
        "current_stage": current_stage,
        "progress_pct": 100.0 if status == "completed" else (float(row[3]) if row[3] is not None else 0),
        "stage_detail": row[4],
        "error_message": row[5],
    }


@router.get("/{order_id}/logs")
async def get_order_logs(
    order_id: int,
    stage: Optional[str] = None,
    since_id: Optional[int] = None,
    limit: int = 50000,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    order_result = await db.execute(select(Order).where(Order.id == order_id))
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    await _check_order_access_async(order, user, db)

    query = select(OrderLog).where(OrderLog.order_id == order_id)
    if stage:
        query = query.where(OrderLog.stage == stage)
    if since_id:
        query = query.where(OrderLog.id > since_id)
    query = query.order_by(OrderLog.created_at.asc()).limit(min(limit, 50000))

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
                "metadata": log.metadata_json or {},
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
    await _check_order_access_async(order, user, db)

    output_dir = Path(settings.OUTPUT_DIR) / order.order_code
    if not output_dir.exists():
        return {"files": []}

    files = []
    for f in output_dir.glob("*.png"):
        if any(f.name.startswith(p) for p in VECTOR_PLOT_PREFIXES):
            files.append(f.name)
    files.sort()
    return {"files": files}


# ── v9.17: Protein class prediction from enriched UniProt/GO data ───────────

# UniProt keyword IDs that indicate specific protein classes
_KW_RECEPTOR = {"KW-0675"}           # Receptor
_KW_KINASE = {"KW-0418"}             # Kinase
_KW_TF = {"KW-0823"}                 # Transcription factor
_KW_PHOSPHATASE = {"KW-0904"}        # Phosphatase
_KW_MEMBRANE = {"KW-0472", "KW-1003"}  # Membrane, Cell membrane
_KW_TRANSDUCER = {"KW-0807"}         # Signal transducer
_KW_ADAPTOR = {"KW-0021"}            # Adaptor protein
_KW_UBIQUITIN = {"KW-0832"}          # Ubl conjugation (substrate)
_KW_E3_LIGASE = {"KW-0833"}          # Ubiquitin ligase (E3)
_KW_DUB = {"KW-0256"}                # Deubiquitinase — note: KW-0256 is ER but we use GO for DUB
_KW_PROTEASE = {"KW-0645"}           # Protease
_KW_CHAPERONE = {"KW-0143"}          # Chaperone
_KW_CYTOSKELETAL = {"KW-0206"}       # Cytoskeleton
_KW_AUTOPHAGY = {"KW-0072"}          # Autophagy
# Exclusion keywords: metabolic enzymes, structural proteins, ribosomal, etc.
# These proteins should NOT be classified as Receptor/TF even if they have moonlighting GO terms
_KW_METABOLIC = {
    "KW-0324",  # Glycolysis
    "KW-0274",  # FAD
    "KW-0560",  # Oxidoreductase
    "KW-0456",  # Lyase
    "KW-0808",  # Transferase
    "KW-0413",  # Isomerase
    "KW-0378",  # Hydrolase
    "KW-0436",  # Ligase
    "KW-0443",  # Lipid metabolism
    "KW-0665",  # Pyridoxal phosphate
    "KW-0816",  # Tricarboxylic acid cycle
    "KW-0312",  # Gluconeogenesis
}
_KW_RIBOSOMAL = {"KW-0687", "KW-0689"}  # Ribosomal protein (large/small subunit)
_KW_STRUCTURAL = {"KW-0206"}            # Cytoskeleton (already in _KW_CYTOSKELETAL)
_KW_NUCLEAR = {"KW-0539", "KW-0547", "KW-0597"}  # Nucleus, Nucleolus, Phosphoprotein(nuclear)
_KW_RNA_BINDING = {"KW-0694"}          # RNA-binding
_KW_SPLICING = {"KW-0747"}             # mRNA splicing

# GO molecular function terms for DUB detection (KW does not cover DUBs well)
_GO_DUB_TERMS = {
    "GO:0004843",  # thiol-dependent ubiquitinyl hydrolase activity
    "GO:0036459",  # thiol-dependent deubiquitinase activity
    "GO:0101005",  # deubiquitinase activity
    "GO:0004221",  # obsolete ubiquitin thiolesterase activity
}
_GO_E3_TERMS = {
    "GO:0061630",  # ubiquitin protein ligase activity
    "GO:0004842",  # ubiquitin-protein transferase activity
    "GO:0019787",  # ubiquitin-like protein transferase activity
}
# Strict receptor GO terms: only transmembrane/cell-surface signaling receptors
_GO_RECEPTOR_TERMS = {
    "GO:0004888",  # transmembrane signaling receptor activity
    "GO:0004930",  # G protein-coupled receptor activity
    "GO:0004872",  # receptor activity
    # GO:0038023 (signaling receptor) and GO:0005057 (signal transducer) removed:
    # too broad, causes false positives for metabolic enzymes with moonlighting roles
}
_GO_KINASE_TERMS = {
    "GO:0004672",  # protein kinase activity
    "GO:0004713",  # protein tyrosine kinase activity
    "GO:0004674",  # protein serine/threonine kinase activity
    "GO:0004675",  # receptor protein serine/threonine kinase activity
    "GO:0004714",  # transmembrane receptor protein tyrosine kinase activity
}
# Strict TF GO terms: require primary TF function, not moonlighting
_GO_TF_TERMS = {
    "GO:0003700",  # DNA-binding transcription factor activity
    "GO:0001228",  # DNA-binding transcription activator activity, RNA pol II-specific
    # GO:0001227 removed: DNA-binding transcription repressor — too broad,
    # many metabolic enzymes (Eno1, Pkm) carry this as moonlighting annotation
}
_GO_PHOSPHATASE_TERMS = {
    "GO:0004721",  # phosphoprotein phosphatase activity
    "GO:0004725",  # protein tyrosine phosphatase activity
    "GO:0004722",  # protein serine/threonine phosphatase activity
    "GO:0004726",  # non-membrane spanning protein tyrosine phosphatase activity
    "GO:0017018",  # myosin phosphatase activity
}
# GO terms that indicate metabolic enzyme (used for exclusion)
_GO_METABOLIC_ENZYME_TERMS = {
    "GO:0004634",  # phosphopyruvate hydratase activity (Enolase)
    "GO:0004332",  # fructose-bisphosphate aldolase activity
    "GO:0004743",  # pyruvate kinase activity
    "GO:0004396",  # hexokinase activity
    "GO:0004616",  # phosphoglucose isomerase activity
    "GO:0004369",  # glycerol-3-phosphate dehydrogenase activity
    "GO:0004738",  # pyruvate decarboxylase activity
    "GO:0003824",  # catalytic activity (broad — only used as secondary exclusion)
}
# GO CC terms that confirm true receptor localization
_GO_RECEPTOR_CC_TERMS = {
    "GO:0005886",  # plasma membrane
    "GO:0009986",  # cell surface
    "GO:0005887",  # integral component of plasma membrane
    "GO:0016021",  # integral component of membrane
}


def _predict_protein_class(ptm: dict, ptm_type: str) -> dict:
    """Predict protein class from enriched UniProt/GO data.

    Returns a dict with:
      - role: primary role label (e.g. 'Receptor', 'Kinase', 'E3 ligase')
      - confidence: 'high' | 'medium' | 'low'
      - tags: list of all applicable role tags for multi-label display
      - ubi_context: ubiquitylation-specific context (only for ubi mode)
    """
    rag = ptm.get("rag_enrichment", {})
    if not rag:
        # Older enriched files may store fields at top level
        rag = ptm

    localization = rag.get("localization", []) or []
    function_summary = (rag.get("function_summary", "") or "").lower()
    go_mf_raw = rag.get("go_terms", {}).get("molecular_function", []) or []
    go_cc_raw = rag.get("go_terms", {}).get("cellular_component", []) or []
    go_bp_raw = rag.get("go_terms", {}).get("biological_process", []) or []
    keywords_raw = rag.get("keywords", []) or []
    protein_families = " ".join(rag.get("protein_families", []) or []).lower()

    # Normalize: extract GO IDs from "GO:xxxxxxx:label" strings
    def _go_ids(terms):
        ids = set()
        for t in terms:
            if isinstance(t, str) and t.startswith("GO:"):
                ids.add(t.split(":")[0] + ":" + t.split(":")[1])
        return ids

    go_mf_ids = _go_ids(go_mf_raw)
    go_cc_ids = _go_ids(go_cc_raw)
    go_bp_ids = _go_ids(go_bp_raw)

    # Normalize keyword IDs
    kw_ids = set()
    for kw in keywords_raw:
        if isinstance(kw, dict):
            kw_ids.add(kw.get("id", ""))
        elif isinstance(kw, str):
            kw_ids.add(kw)

    # Normalize localization strings
    loc_lower = " ".join(localization).lower()

    # ── v9.17.1: Exclusion flags — prevent moonlighting GO terms from causing false positives
    # Metabolic enzymes (Eno1, Pkm, Aldoa, etc.) carry TF/receptor GO terms as moonlighting
    is_metabolic_enzyme = bool(
        (kw_ids & _KW_METABOLIC) or
        (go_mf_ids & _GO_METABOLIC_ENZYME_TERMS) or
        any(w in function_summary for w in ("glycolysis", "gluconeogenesis", "glycolytic", "enolase",
                                             "aldolase", "pyruvate", "phosphoglycerate",
                                             "oxidoreductase", "dehydrogenase", "isomerase",
                                             "hydratase", "lyase", "aminotransferase"))
    )
    is_ribosomal = bool(
        (kw_ids & _KW_RIBOSOMAL) or
        any(w in function_summary for w in ("ribosomal protein", "ribosome", "translation",
                                             "40s ribosomal", "60s ribosomal"))
    )
    # RNA helicase / RNA-binding (Dhx9, Ddx etc.) — should not be Cyto or Chap
    is_rna_helicase = bool(
        any(w in function_summary for w in ("rna helicase", "rna-dependent", "helicase activity",
                                             "dead-box", "deah-box", "rna unwinding",
                                             "rna binding", "rna-binding")) or
        (kw_ids & _KW_RNA_BINDING) or
        (kw_ids & _KW_SPLICING)
    )
    # Splicing factors (Srsf1, Srsf6, Tra2b etc.)
    is_splicing_factor = bool(
        any(w in function_summary for w in ("splicing factor", "pre-mrna splicing",
                                             "serine/arginine-rich", "sr protein",
                                             "rna splicing", "mrna processing")) or
        (kw_ids & _KW_SPLICING)
    )
    # Structural proteins (actin, tubulin, vimentin, lamin, etc.)
    is_structural = bool(
        any(w in function_summary for w in ("cytoskeletal", "structural constituent",
                                             "actin", "tubulin", "intermediate filament",
                                             "nuclear lamina", "lamin"))
    )
    # Nuclear/nucleolar proteins (Lmna, Nolc1, Tcof1, Npm1, etc.)
    # RNA helicases are excluded even if they localize to nucleus (Dhx9 false positive)
    is_nuclear = bool(
        not is_rna_helicase and (
            (kw_ids & _KW_NUCLEAR) or
            any(w in loc_lower for w in ("nucleus", "nucleolus", "nucleoplasm", "nuclear")) or
            any(w in function_summary for w in ("nucleolar", "nucleolus", "nuclear body",
                                                 "chromatin", "histone", "nuclear pore",
                                                 "nuclear lamina", "lamin"))
        )
    )
    # Nucleolar proteins (Nolc1, Tcof1, Npm1): ribosome biogenesis in nucleolus
    # These are ribosome-related but NOT ribosomal proteins — they should get Nuc badge
    is_nucleolar_non_ribosomal = bool(
        is_ribosomal and  # flagged as ribosomal due to 'ribosome biogenesis' keyword
        any(w in loc_lower for w in ("nucleolus",)) and
        not any(w in function_summary for w in ("ribosomal protein", "40s ribosomal", "60s ribosomal",
                                                  "component of the"))
    )

    tags = []
    confidence_scores = {}  # role -> score (higher = more confident)

    # ── Receptor ──────────────────────────────────────────────────────────────
    receptor_score = 0
    if not (is_metabolic_enzyme or is_ribosomal or is_rna_helicase or is_splicing_factor):
        if kw_ids & _KW_RECEPTOR:
            receptor_score += 4  # UniProt KW is most authoritative
        if go_mf_ids & _GO_RECEPTOR_TERMS:
            receptor_score += 3
        # Require CC confirmation: must be on plasma membrane / cell surface
        if go_cc_ids & _GO_RECEPTOR_CC_TERMS:
            receptor_score += 2
        if "receptor" in function_summary:
            if not any(w in function_summary for w in ("nuclear receptor coactivator", "co-receptor",
                                                        "receptor-associated", "receptor-interacting")):
                receptor_score += 2
        if "receptor" in protein_families:
            receptor_score += 2
        # v9.18: additional receptor family keywords in function_summary
        if any(w in function_summary for w in (
            "growth factor receptor", "hormone receptor", "cytokine receptor",
            "tyrosine kinase receptor", "receptor tyrosine kinase",
            "g protein-coupled", "gpcr", "integrin", "toll-like receptor",
            "notch", "frizzled", "smoothened", "tgf-beta receptor",
            "insulin receptor", "igf", "epidermal growth factor receptor",
            "fibroblast growth factor receptor", "vascular endothelial growth factor receptor",
        )):
            receptor_score += 2
    # Threshold raised to 5 to require at least 2 strong signals
    if receptor_score >= 5:
        tags.append("Receptor")
        confidence_scores["Receptor"] = receptor_score

    # ── Kinase ────────────────────────────────────────────────────────────────
    kinase_score = 0
    if kw_ids & _KW_KINASE:
        kinase_score += 3
    if go_mf_ids & _GO_KINASE_TERMS:
        kinase_score += 3
    # v9.17.3: expanded function_summary matching — covers cases where keywords are absent
    # (existing enriched data before v9.17 lacks keywords field)
    _KINASE_FUNC_PATTERNS = (
        "protein kinase", "serine/threonine-protein kinase", "tyrosine-protein kinase",
        "serine/threonine kinase", "tyrosine kinase", "cyclin-dependent kinase",
        "map kinase", "mitogen-activated protein kinase", "receptor kinase",
        "dual-specificity kinase", "dual specificity kinase",
        "phosphorylates", "autophosphorylat",
    )
    if any(p in function_summary for p in _KINASE_FUNC_PATTERNS) or "kinase" in protein_families:
        kinase_score += 2
    # RTK = Receptor + Kinase + confirmed membrane
    if kinase_score >= 3 and receptor_score >= 3:
        tags.append("RTK")
        confidence_scores["RTK"] = kinase_score + receptor_score
    elif kinase_score >= 3:
        tags.append("Kinase")
        confidence_scores["Kinase"] = kinase_score

    # ── Transcription Factor ──────────────────────────────────────────────────
    tf_score = 0
    if not (is_metabolic_enzyme or is_ribosomal or is_structural):
        if kw_ids & _KW_TF:
            tf_score += 4  # UniProt KW-0823 is authoritative
        if go_mf_ids & _GO_TF_TERMS:  # strict set: GO:0003700, GO:0001228 only
            tf_score += 3
        if "transcription factor" in function_summary or "transcription factor" in protein_families:
            tf_score += 2
        if "nucleus" in loc_lower and not is_metabolic_enzyme:
            tf_score += 1
    # Threshold raised to 4 to require KW or GO confirmation
    if tf_score >= 4:
        tags.append("TF")
        confidence_scores["TF"] = tf_score

    # ── Phosphatase ───────────────────────────────────────────────────────────
    phos_score = 0
    if kw_ids & _KW_PHOSPHATASE:
        phos_score += 3
    if go_mf_ids & _GO_PHOSPHATASE_TERMS:
        phos_score += 3
    if "phosphatase" in function_summary or "phosphatase" in protein_families:
        phos_score += 2
    if phos_score >= 3:
        tags.append("Phosphatase")
        confidence_scores["Phosphatase"] = phos_score

    # ── Adaptor / Scaffold ────────────────────────────────────────────────────
    adaptor_score = 0
    if kw_ids & _KW_ADAPTOR:
        adaptor_score += 3
    if "adaptor" in function_summary or "scaffold" in function_summary:
        adaptor_score += 2
    if "adapter" in function_summary or "docking" in function_summary:
        adaptor_score += 1
    if adaptor_score >= 2:
        tags.append("Adaptor")
        confidence_scores["Adaptor"] = adaptor_score

    # ── Chaperone ─────────────────────────────────────────────────────────────
    # Exclude ribosomal proteins and RNA helicases from Chaperone classification
    if not (is_ribosomal or is_rna_helicase):
        if kw_ids & _KW_CHAPERONE or "chaperone" in function_summary:
            tags.append("Chaperone")
            confidence_scores["Chaperone"] = 3

    # ── Cytoskeletal ──────────────────────────────────────────────────────────
    # Exclude RNA helicases from Cytoskeletal classification (Dhx9 false positive)
    if not (is_rna_helicase or is_splicing_factor):
        if kw_ids & _KW_CYTOSKELETAL or "cytoskeleton" in loc_lower:
            tags.append("Cytoskeletal")
            confidence_scores["Cytoskeletal"] = 2

    # ── Nuclear / Nucleolar ───────────────────────────────────────────────────
    # Nuclear — only if no strong functional badge
    # Exclude metabolic enzymes and ribosomal proteins (in nucleus but not 'nuclear proteins')
    # RNA helicases already excluded via is_nuclear flag
    if not is_metabolic_enzyme and is_nuclear:
        if not any(r in confidence_scores for r in ("RTK", "Receptor", "Kinase", "TF",
                                                     "Phosphatase", "E3 ligase", "DUB")):
            tags.append("Nuclear")
            confidence_scores["Nuclear"] = 2
    # Nucleolar non-ribosomal proteins (Nolc1, Tcof1 etc.)
    elif is_nucleolar_non_ribosomal and not is_metabolic_enzyme:
        if not any(r in confidence_scores for r in ("RTK", "Receptor", "Kinase", "TF",
                                                     "Phosphatase", "E3 ligase", "DUB")):
            tags.append("Nuclear")
            confidence_scores["Nuclear"] = 2
    # ── Ubiquitylation-specific roles ─────────────────────────────────────────
    ubi_context = None
    if ptm_type in ("ubiquitylation", "ubiquitination"):
        # E3 Ligase
        e3_score = 0
        if kw_ids & _KW_E3_LIGASE:
            e3_score += 3
        if go_mf_ids & _GO_E3_TERMS:
            e3_score += 3
        if "e3 ligase" in function_summary or "ubiquitin ligase" in function_summary:
            e3_score += 2
        if "ring" in protein_families or "hect" in protein_families or "rbr" in protein_families:
            e3_score += 2
        if e3_score >= 3:
            tags.append("E3 ligase")
            confidence_scores["E3 ligase"] = e3_score

        # DUB (Deubiquitinase)
        dub_score = 0
        if go_mf_ids & _GO_DUB_TERMS:
            dub_score += 3
        if "deubiquitin" in function_summary or "deubiquitylat" in function_summary:
            dub_score += 3
        if "ubiquitin" in protein_families and ("hydrolase" in protein_families or "protease" in protein_families):
            dub_score += 2
        if dub_score >= 3:
            tags.append("DUB")
            confidence_scores["DUB"] = dub_score

        # Autophagy receptor
        if kw_ids & _KW_AUTOPHAGY or "autophagy" in function_summary:
            if "receptor" in function_summary or "cargo" in function_summary:
                tags.append("Autophagy receptor")
                confidence_scores["Autophagy receptor"] = 3

        # Determine ubi_context from chain types + localization
        chain_types = []
        regulation = rag.get("regulation", {})
        if isinstance(regulation, dict):
            chain_types = regulation.get("chain_types", []) or []
        # Also check ubi_chain_classification if present
        ubi_chain = rag.get("ubi_chain_classification", {})
        if isinstance(ubi_chain, dict) and ubi_chain.get("chain_type"):
            chain_types = list(set(chain_types + [ubi_chain["chain_type"]]))

        if chain_types:
            is_membrane = "cell membrane" in loc_lower or "plasma membrane" in loc_lower
            is_receptor_tag = "Receptor" in tags or "RTK" in tags
            if "K63" in chain_types and (is_membrane or is_receptor_tag):
                ubi_context = "K63 endocytosis"
            elif "K48" in chain_types and (is_membrane or is_receptor_tag):
                ubi_context = "K48 degradation"
            elif "K48" in chain_types:
                ubi_context = "K48 proteasomal"
            elif "K63" in chain_types:
                ubi_context = "K63 signaling"
            elif "K27" in chain_types or "K29" in chain_types or "K33" in chain_types:
                ubi_context = "atypical chain"
            elif any(ct in chain_types for ct in ("Mono", "monoubiquitin", "mono")):
                ubi_context = "mono-Ub endocytosis"

    # ── Determine primary role and confidence ─────────────────────────────────
    # Priority order for primary role display
    priority = ["RTK", "E3 ligase", "DUB", "Receptor", "Kinase", "TF",
                "Phosphatase", "Adaptor", "Chaperone", "Autophagy receptor",
                "Cytoskeletal", "Nuclear"]
    primary_role = None
    for p in priority:
        if p in confidence_scores:
            primary_role = p
            break

    if primary_role is None:
        # v9.17.3: Remove Membrane protein fallback — too generic and misleading
        # (Anxa2, Eno1 etc. have 'Cell membrane' keyword but are not membrane-signaling proteins)
        # Only show badge if there is a meaningful functional classification
        primary_role = "Other"

    # Confidence based on top score
    top_score = confidence_scores.get(primary_role, 0)
    if top_score >= 5:
        confidence = "high"
    elif top_score >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    result = {
        "role": primary_role,
        "confidence": confidence,
        "tags": tags,
    }
    if ubi_context:
        result["ubi_context"] = ubi_context
    return result


@router.get("/{order_id}/vector-plot-data")
async def get_vector_plot_data(
    order_id: int,
    lock_receptor: bool = Query(False, description="True이면 저장된 receptor 결과를 고정하고 재계산하지 않음"),
    force_refresh: bool = Query(False, description="True이면 캐시를 무시하고 receptor를 강제 재계산"),
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
    await _check_order_access_async(order, user, db)

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
                    pc_used_raw = row.get("Control_Pseudocount_Used", "")
                    pc_used = pc_used_raw.strip().lower() in ("true", "1", "yes") if pc_used_raw else False
                    # p_value / q_value (v9.25: Welch's t-test + BH correction)
                    p_val_raw = row.get("p_value", "")
                    q_val_raw = row.get("q_value", "")
                    try:
                        p_val = float(p_val_raw) if p_val_raw and p_val_raw.strip().lower() not in ("", "nan") else None
                    except (ValueError, TypeError):
                        p_val = None
                    try:
                        q_val = float(q_val_raw) if q_val_raw and q_val_raw.strip().lower() not in ("", "nan") else None
                    except (ValueError, TypeError):
                        q_val = None
                    vector_data.append({
                        "gene": gene,
                        "position": str(pos),
                        "condition": cond,
                        "protein_log2fc": prot_fc,
                        "ptm_relative_log2fc": rel_fc,
                        "ptm_absolute_log2fc": abs_fc,
                        "control_pseudocount_used": pc_used,
                        "p_value": p_val,
                        "q_value": q_val,
                    })
            break

    # Load Top N PTMs — prefer enriched JSON, fall back to TSV-based selection
    top_n_ptms = []
    top_n_setting = (order.report_options or {}).get("top_n_ptms", 20)
    enriched_path = output_dir / f"enriched_ptm_data{file_suffix}.json"
    ptm_type_str = (order.ptm_type or "phosphorylation").lower().strip()

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
                # v9.17: Predict protein class from enriched UniProt/GO data
                protein_class = _predict_protein_class(ptm, ptm_type_str)
                top_n_ptms.append({
                    "gene": str(gene),
                    "position": str(pos),
                    "label": f"{gene} {pos}".strip() or f"{gene}{pos}",
                    "protein_class": protein_class,
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

    # ── v9.18 + v9.19: Infer upstream receptors ──────────────────────────────
    # Three sources:
    #   (A) upstream_regulators from enriched data (text-based, biased)
    #   (B) Reactome pathway mapping: kinase → receptor (unbiased, cached)
    #   (C) Treatment-context: order.analysis_context.treatment → known ligand-receptor DB
    from app.services.ligand_receptor_db import _RECEPTOR_DOWNSTREAM_KINASES
    inferred_receptors = []

    # ═══════════════════════════════════════════════════════════════════════════
    # RECEPTOR INFERENCE CACHING (v9.40)
    # ═══════════════════════════════════════════════════════════════════════════
    _cached_receptor_data = order.receptor_inference_data or {}
    _cached_receptors = _cached_receptor_data.get("receptors", [])
    _use_cached = False

    if lock_receptor and _cached_receptors:
        # 결정론적 모드: 이미 저장된 결과를 고정하여 반환
        _use_cached = True
        logging.getLogger("vector_plot").info(
            f"Receptor inference: lock_receptor=True, returning {len(_cached_receptors)} cached receptors"
        )
    elif not force_refresh and _cached_receptors:
        # 일반 캐시 히트: top_n이 변경되지 않았으면 캐시 사용
        _cached_top_n = _cached_receptor_data.get("top_n_setting")
        if _cached_top_n == top_n_setting:
            _use_cached = True
            logging.getLogger("vector_plot").info(
                f"Receptor inference: cache hit (top_n={top_n_setting}), "
                f"returning {len(_cached_receptors)} cached receptors"
            )
        else:
            logging.getLogger("vector_plot").info(
                f"Receptor inference: top_n changed ({_cached_top_n} -> {top_n_setting}), recalculating"
            )

    if _use_cached:
        inferred_receptors = _cached_receptors
        _cowave_analysis = _cached_receptor_data.get("cowave_analysis")  # v9.42: restore from cache

    if not _use_cached:
        # --- Source A: upstream_regulators (existing, kept for backward compat) ---
        literature_receptors: dict = {}  # receptor_name -> {ptm_labels, class}
        if enriched_path.exists():
            from collections import defaultdict
            from app.services.ligand_receptor_db import _RECEPTOR_DOWNSTREAM_KINASES
            receptor_ptm_map: dict = defaultdict(list)
            for ptm in enriched:
                gene = ptm.get("gene") or ptm.get("Gene.Name", "")
                pos  = ptm.get("position") or ptm.get("PTM_Position", "")
                label = f"{gene} {pos}".strip()
                rag = ptm.get("rag_enrichment", {})
                reg = rag.get("regulation", {}) if isinstance(rag, dict) else {}
                upstream = reg.get("upstream_regulators", []) if isinstance(reg, dict) else []
                if not isinstance(upstream, list):
                    upstream = []
                for ur in upstream:
                    ur_name = ur.strip() if isinstance(ur, str) else ""
                    if not ur_name:
                        continue
                    ur_lower = ur_name.lower()
                    is_receptor = any(kw in ur_lower for kw in (
                        "receptor", "egfr", "erbb", "vegfr", "fgfr", "igf1r", "insr",
                        "pdgfr", "met", "ret", "kit", "axl", "tie", "ror", "alk",
                        "trkb", "trka", "trkc", "ntrk", "ros1", "musk",
                        "integrin", "notch", "frizzled", "fzd", "smoothened", "smo",
                        "gpcr", "adrb", "adra", "chrm", "htr", "drd", "oprm",
                        "tlr", "il-", "tnfr", "ifnar", "ifngr", "tgfbr", "bmpr",
                        "growth factor receptor", "hormone receptor", "cytokine receptor",
                        "immune receptor", "toll-like",
                    ))
                    if is_receptor:
                        receptor_ptm_map[ur_name].append(label)
            for rec_name, ptm_labels in sorted(receptor_ptm_map.items(),
                                                key=lambda x: len(x[1]), reverse=True):
                rec_lower = rec_name.lower()
                if any(kw in rec_lower for kw in ("egfr","erbb","vegfr","fgfr","igf1r",
                                                   "insr","pdgfr","met","ret","kit",
                                                   "axl","tie","ror","alk","trkb","trka",
                                                   "trkc","ntrk","ros1","musk")):
                    rec_class = "RTK"
                elif any(kw in rec_lower for kw in ("integrin",)):
                    rec_class = "Integrin"
                elif any(kw in rec_lower for kw in ("notch","frizzled","fzd","smoothened","smo")):
                    rec_class = "Developmental"
                elif any(kw in rec_lower for kw in ("gpcr","adrb","adra","chrm","htr","drd","oprm")):
                    rec_class = "GPCR"
                elif any(kw in rec_lower for kw in ("tlr","tnfr","il-","ifnar","ifngr")):
                    rec_class = "Cytokine/Immune"
                elif any(kw in rec_lower for kw in ("tgfbr","bmpr")):
                    rec_class = "TGFβ"
                else:
                    rec_class = "Receptor"
                literature_receptors[rec_name] = {
                    "name": rec_name,
                    "receptor_class": rec_class,
                    "downstream_ptm_count": len(ptm_labels),
                    "downstream_ptms": ptm_labels[:10],
                    "via_kinases": [],
                    "source": "literature",
                    "has_receptor_specific_db": False,
                }

        # --- Source B: Reactome pathway mapping (kinase → receptor) ---
        # v9.19.3: Use kinase_analysis_data from DB (populated by Kinase Module Analysis)
        # as the PRIMARY source of kinase names. This includes iPTMnet + UniProt API results
        # that are not stored in enriched JSON. Falls back to enriched JSON parsing.
        reactome_receptors: dict = {}  # receptor_name -> {info}
        from collections import defaultdict
        kinase_names_set: set = set()
        kinase_ptm_map: dict = defaultdict(set)  # kinase_name -> {ptm_labels}
        try:

            # ── Primary source: order.kinase_analysis_data (from Kinase Module Analysis) ──
            # This contains kinases from ALL 8 sources including iPTMnet/UniProt API
            kad = order.kinase_analysis_data or {}
            kinase_modules = kad.get("kinase_modules", [])
            if kinase_modules:
                for km in kinase_modules:
                    kinase_name = km.get("kinase", "") or km.get("canonical", "")
                    if not kinase_name:
                        continue
                    kinase_names_set.add(kinase_name.strip())
                    # Build kinase → PTM map from module members
                    for member in km.get("members", []):
                        ptm_label = member.get("label", "") or member.get("key", "")
                        if ptm_label:
                            # Normalize key format "GENE_POS" → "GENE POS"
                            kinase_ptm_map[kinase_name.strip()].add(
                                ptm_label.replace("_", " ") if "_" in ptm_label and " " not in ptm_label else ptm_label
                            )
                logging.getLogger("vector_plot").info(
                    f"Reactome: {len(kinase_names_set)} kinases from kinase_analysis_data"
                )

            # ── v9.41: E3 Module Integration for Ubiquitylation orders ──
            # If ptm_type is ubiquitylation, also extract E3 ligase names from
            # kinase_analysis_data (stored by Kinase Annotation Node's Ubi Suite)
            if ptm_type_str in ("ubiquitylation", "ubiquitination"):
                e3_modules_data = kad.get("ubi_e3_modules", {})
                if isinstance(e3_modules_data, dict):
                    for e3m in e3_modules_data.get("e3_modules", []):
                        e3_name = e3m.get("e3_ligase", "") or e3m.get("canonical", "")
                        if e3_name and e3_name.strip():
                            kinase_names_set.add(e3_name.strip())
                            # Also add E3 → PTM map for substrate tracking
                            for sub in e3m.get("confirmed_substrates", []) + e3m.get("inferred_substrates", []):
                                sub_label = sub.get("label", "") or sub.get("key", "")
                                if sub_label:
                                    kinase_ptm_map[e3_name.strip()].add(
                                        sub_label.replace("_", " ") if "_" in sub_label and " " not in sub_label else sub_label
                                    )
                    if e3_modules_data.get("e3_modules"):
                        logging.getLogger("vector_plot").info(
                            f"E3 Module Integration: added {len(e3_modules_data['e3_modules'])} E3 ligases to kinase_names_set"
                        )

            # ── Fallback: enriched JSON parsing (if kinase_analysis_data is empty) ──
            if not kinase_names_set and enriched_path.exists():
                _kinase_kw = {
                    "kinase", "cdk", "mapk", "erk", "akt", "pkc", "pkb",
                    "gsk", "ck1", "ck2", "dyrk", "hipk", "mtor", "ampk",
                    "plk", "aur", "nek", "chk", "atm", "atr",
                    "jak", "src", "abl", "lyn", "fyn", "lck", "syk",
                    "raf", "mek", "jnk", "p38", "pi3k", "pdk",
                    "cam", "rock", "pak", "rsk", "s6k", "sgk",
                }
                # v9.41: Add E3 ligase keywords for ubiquitylation orders
                if ptm_type_str in ("ubiquitylation", "ubiquitination"):
                    _kinase_kw.update({
                        "e3", "ligase", "ubiquitin", "nedd4", "mdm2", "trim",
                        "cbl", "vhl", "traf", "itch", "wwp", "huwe", "chip",
                        "parkin", "smurf", "rnf", "march", "hectd", "ube3",
                        "fbxw", "skp2", "btrc", "keap1", "spop", "cullin",
                    })
                for ptm in enriched:
                    rag = ptm.get("rag_enrichment", {})
                    if not isinstance(rag, dict):
                        continue
                    gene = ptm.get("gene") or ptm.get("Gene.Name", "")
                    pos = ptm.get("position") or ptm.get("PTM_Position", "")
                    label = f"{gene} {pos}".strip()
                    # kinase_prediction
                    kp = rag.get("kinase_prediction", {})
                    if isinstance(kp, dict):
                        for pk in kp.get("predicted_kinases", []):
                            kname = pk.get("kinase", "") if isinstance(pk, dict) else (pk if isinstance(pk, str) else "")
                            if kname and kname.strip():
                                kinase_names_set.add(kname.strip())
                                kinase_ptm_map[kname.strip()].add(label)
                    # regulation.kinase_substrate
                    reg = rag.get("regulation", {})
                    if isinstance(reg, dict):
                        for ks in reg.get("kinase_substrate", []):
                            if isinstance(ks, dict) and ks.get("kinase"):
                                kinase_names_set.add(ks["kinase"].strip())
                                kinase_ptm_map[ks["kinase"].strip()].add(label)
                    # fulltext_analysis key_findings
                    ft = rag.get("fulltext_analysis", {})
                    if isinstance(ft, dict):
                        _ft_re = re.compile(
                            r'(?:substrate\s+of|phosphorylated\s+by|target\s+of|regulated\s+by)'
                            r'\s+([A-Z][A-Za-z0-9]{1,10})',
                            re.IGNORECASE,
                        )
                        for finding in ft.get("key_findings", []):
                            if isinstance(finding, str):
                                for m in _ft_re.finditer(finding):
                                    kname = m.group(1).strip()
                                    if kname and len(kname) > 1:
                                        kinase_names_set.add(kname)
                                        kinase_ptm_map[kname].add(label)
                    # abstract_analysis
                    aa = rag.get("abstract_analysis", {})
                    if isinstance(aa, dict):
                        for key_name in ("kinases", "upstream_kinases", "predicted_kinases"):
                            for item in aa.get(key_name, []):
                                kname = item if isinstance(item, str) else (item.get("kinase") or item.get("name", "") if isinstance(item, dict) else "")
                                if kname and kname.strip():
                                    kinase_names_set.add(kname.strip())
                                    kinase_ptm_map[kname.strip()].add(label)
                    # string_interactions — prefer string_db.interactions (dict list), fallback to string_interactions (may be str list)
                    _sdb = rag.get("string_db", {})
                    _sdb_ints = _sdb.get("interactions", []) if isinstance(_sdb, dict) else []
                    if _sdb_ints:
                        _si_list = _sdb_ints
                    else:
                        import re as _re_si
                        _si_list = []
                        for _s in (rag.get("string_interactions", []) or []):
                            if isinstance(_s, dict):
                                _si_list.append(_s)
                            elif isinstance(_s, str):
                                _m = _re_si.match(r"^(.+)\(([0-9.]+)\)$", _s.strip())
                                if _m:
                                    _si_list.append({"partner": _m.group(1), "score": float(_m.group(2))})
                    for si in _si_list:
                        partner = si.get("preferredName_B") or si.get("partner") or ""
                        score = si.get("score", 0)
                        if isinstance(score, float) and score <= 1.0:
                            score = score * 1000
                        if partner and score >= 700:
                            pl = partner.lower()
                            if any(kw in pl for kw in _kinase_kw):
                                kinase_names_set.add(partner.strip())
                                kinase_ptm_map[partner.strip()].add(label)

            if kinase_names_set:
                from app.services.reactome_client import get_receptors_for_kinases
                # ── Wave-aware kinase selection for Reactome query ──
                # Instead of just taking top 20 alphabetically, ensure diversity
                # by including kinases from different temporal waves
                _wave_diverse_kinases: list[str] = []
                try:
                    kad_for_waves = order.kinase_analysis_data or {}
                    _wkp = kad_for_waves.get("wave_kinase_profile", [])
                    if _wkp:
                        # Take top kinases from each wave (ensures temporal diversity)
                        for _wave in _wkp:
                            for _wk in _wave.get("kinases", [])[:4]:
                                _wk_name = _wk.get("canonical", "") or _wk.get("kinase", "")
                                if _wk_name and _wk_name in kinase_names_set:
                                    if _wk_name not in _wave_diverse_kinases:
                                        _wave_diverse_kinases.append(_wk_name)
                except Exception:
                    pass
                # Fill remaining slots with other kinases
                _remaining = [k for k in sorted(kinase_names_set) if k not in _wave_diverse_kinases]
                kinase_list = (_wave_diverse_kinases + _remaining)[:30]  # expanded to 30 for better coverage
                logging.getLogger("vector_plot").info(
                    f"Reactome: querying receptors for {len(kinase_list)} kinases: {kinase_list}"
                )
                kinase_receptor_map = await get_receptors_for_kinases(kinase_list)

                # Aggregate: receptor → {kinases that link to it}
                receptor_kinase_map: dict = defaultdict(lambda: {
                    "kinases": [], "receptor_class": "", "pathway": "", "signaling_pathway": ""
                })
                for kinase_name, receptors in kinase_receptor_map.items():
                    for rec in receptors:
                        rec_name = rec["receptor"]
                        receptor_kinase_map[rec_name]["kinases"].append(kinase_name)
                        if not receptor_kinase_map[rec_name]["receptor_class"]:
                            receptor_kinase_map[rec_name]["receptor_class"] = rec["receptor_class"]
                        if not receptor_kinase_map[rec_name]["pathway"]:
                            receptor_kinase_map[rec_name]["pathway"] = rec.get("pathway", "")
                        if not receptor_kinase_map[rec_name]["signaling_pathway"]:
                            receptor_kinase_map[rec_name]["signaling_pathway"] = rec.get("signaling_pathway", "")

                for rec_name, info in receptor_kinase_map.items():
                    # Count PTMs reachable via this receptor's kinases
                    downstream_ptms = set()
                    for kin in info["kinases"]:
                        downstream_ptms.update(kinase_ptm_map.get(kin, set()))
                    unique_kinases = sorted(set(info["kinases"]))

                    # v9.37: Supplement with receptor-specific kinases from curated DB
                    _b_aliases: list[str] = [rec_name.split("(")[0].strip().upper()]
                    if "(" in rec_name:
                        _b_alias = rec_name.split("(")[1].replace(")", "").strip().upper()
                        if _b_alias:
                            _b_aliases.append(_b_alias)
                    for _ba in list(_b_aliases):
                        _bc = _ba.replace("-", "").replace(" ", "")
                        if _bc != _ba:
                            _b_aliases.append(_bc)

                    _b_rec_specific: set = set()
                    for _ba in _b_aliases:
                        if _ba in _RECEPTOR_DOWNSTREAM_KINASES:
                            _b_rec_specific.update(_RECEPTOR_DOWNSTREAM_KINASES[_ba])

                    _b_has_specific = len(_b_rec_specific) > 0
                    if _b_has_specific:
                        _existing_set = set(unique_kinases)
                        _priority = [k for k in _b_rec_specific
                                     if k in kinase_names_set and k not in _existing_set]
                        unique_kinases = _priority + unique_kinases
                        unique_kinases = unique_kinases[:8]
                        for _pk in _priority:
                            downstream_ptms.update(kinase_ptm_map.get(_pk, set()))

                    reactome_receptors[rec_name] = {
                        "name": rec_name,
                        "receptor_class": info["receptor_class"],
                        "downstream_ptm_count": max(len(downstream_ptms), 1),
                        "downstream_ptms": sorted(downstream_ptms)[:10],
                        "via_kinases": unique_kinases,
                        "pathway": info["pathway"],
                        "signaling_pathway": info["signaling_pathway"],
                        "source": "reactome",
                        "has_receptor_specific_db": _b_has_specific,
                    }
            else:
                logging.getLogger("vector_plot").warning(
                    "Reactome: No kinases found from kinase_analysis_data or enriched data"
                )
        except Exception as e:
            logging.getLogger("vector_plot").warning(f"Reactome receptor lookup failed: {e}")

        # --- Source B-1.5: Curated kinase→receptor DB fallback ---
        # When Reactome API returns few receptors, supplement with curated reverse mapping.
        # This ensures kinase modules that Reactome doesn't cover still get receptor annotations.
        try:
            from app.services.ligand_receptor_db import get_upstream_receptors_for_kinases
            # Identify kinases not yet mapped to any receptor
            _mapped_kinases = set()
            for _ri in reactome_receptors.values():
                _mapped_kinases.update(_ri.get("via_kinases", []))
            _unmapped_kinases = [k for k in kinase_names_set if k not in _mapped_kinases]
            
            if _unmapped_kinases or len(reactome_receptors) < 5:
                # Query curated DB for all kinases (not just unmapped) to maximize coverage
                _curated_results = get_upstream_receptors_for_kinases(list(kinase_names_set))
                _curated_receptor_kinases: dict = {}  # receptor_name -> set of kinases
                for _kin, _recs in _curated_results.items():
                    for _rec_info in _recs:
                        _rn = _rec_info["receptor"]
                        if _rn not in _curated_receptor_kinases:
                            _curated_receptor_kinases[_rn] = {
                                "kinases": set(),
                                "receptor_class": _rec_info["receptor_class"],
                            }
                        _curated_receptor_kinases[_rn]["kinases"].add(_kin)
                
                # Add curated receptors that aren't already in reactome_receptors
                # Build a reverse lookup: curated kinase name → actual kinase_names_set name
                # This handles cases like curated "MAPK1" matching module "ERK1/2"
                _curated_to_actual: dict = {}  # curated_name → actual_name_in_kinase_names_set
                _kinase_names_upper = {k.upper(): k for k in kinase_names_set}
                for _ck in set(k for info in _curated_receptor_kinases.values() for k in info["kinases"]):
                    _ck_upper = _ck.upper()
                    if _ck_upper in _kinase_names_upper:
                        _curated_to_actual[_ck] = _kinase_names_upper[_ck_upper]
                    else:
                        # Try matching via alias: curated "MAPK1" → module "ERK1/2" or "ERK2"
                        for _actual_name in kinase_names_set:
                            _an_upper = _actual_name.upper()
                            # Check if curated name is part of a composite ("ERK1/2" contains "ERK1")
                            if _ck_upper in _an_upper or _an_upper in _ck_upper:
                                _curated_to_actual[_ck] = _actual_name
                                break
                            # Check common aliases
                            if _ck_upper == "ERK1" and "ERK" in _an_upper:
                                _curated_to_actual[_ck] = _actual_name
                                break
                            if _ck_upper == "ERK2" and "ERK" in _an_upper:
                                _curated_to_actual[_ck] = _actual_name
                                break
                            if _ck_upper == "MAPK1" and ("ERK" in _an_upper or "MAPK1" in _an_upper):
                                _curated_to_actual[_ck] = _actual_name
                                break
                            if _ck_upper == "MAPK3" and ("ERK" in _an_upper or "MAPK3" in _an_upper):
                                _curated_to_actual[_ck] = _actual_name
                                break

                _curated_added = 0
                for _rn, _info in _curated_receptor_kinases.items():
                    _raw_kins = sorted(_info["kinases"])[:8]
                    # Map curated kinase names to actual names in kinase_names_set
                    _via_kins_mapped = []
                    _via_kins_display = []
                    for _rk in _raw_kins:
                        if _rk in _curated_to_actual:
                            _actual = _curated_to_actual[_rk]
                            if _actual not in _via_kins_mapped:
                                _via_kins_mapped.append(_actual)
                                _via_kins_display.append(_actual)
                        else:
                            _via_kins_display.append(_rk)
                    
                    # Use mapped kinases for PTM lookup, display names for via_kinases
                    _ds_ptms = set()
                    for _vk in _via_kins_mapped:
                        _ds_ptms.update(kinase_ptm_map.get(_vk, set()))
                    # Also try original curated names as fallback
                    if not _ds_ptms:
                        for _vk in _raw_kins:
                            _ds_ptms.update(kinase_ptm_map.get(_vk, set()))
                    
                    # Use mapped kinases (that have PTM data) for display
                    _final_via = _via_kins_mapped if _via_kins_mapped else _via_kins_display[:8]
                    
                    if _rn not in reactome_receptors:
                        # Relaxed condition: add if we have at least 1 mapped kinase with PTMs,
                        # OR if 2+ kinases from our data map to this receptor
                        if len(_via_kins_mapped) >= 1 or len(_ds_ptms) >= 3:
                            reactome_receptors[_rn] = {
                                "name": _rn,
                                "receptor_class": _info["receptor_class"],
                                "downstream_ptm_count": max(len(_ds_ptms), len(_via_kins_mapped)),
                                "downstream_ptms": sorted(_ds_ptms)[:20],
                                "via_kinases": _final_via[:8],
                                "pathway": f"Curated: {_rn} → {', '.join(_final_via[:3])}",
                                "signaling_pathway": f"Signaling by {_rn}",
                                "source": "curated_kinase_receptor_db",
                                "has_receptor_specific_db": True,
                            }
                            _curated_added += 1
                    else:
                        # Supplement existing receptor with additional kinases
                        _existing = reactome_receptors[_rn]
                        _existing_via = set(_existing.get("via_kinases", []))
                        _new_via = [k for k in _final_via if k not in _existing_via]
                        if _new_via:
                            _existing["via_kinases"] = (list(_existing_via) + _new_via)[:8]
                            # Update PTM count
                            _all_ptms = set()
                            for _vk in _existing["via_kinases"]:
                                _all_ptms.update(kinase_ptm_map.get(_vk, set()))
                            _existing["downstream_ptm_count"] = max(len(_all_ptms), _existing["downstream_ptm_count"])
                            _existing["downstream_ptms"] = sorted(_all_ptms)[:20]
                
                logging.getLogger("vector_plot").info(
                    f"Curated DB (Source B-1.5): Added {_curated_added} receptors, "
                    f"supplemented existing. Total receptors now: {len(reactome_receptors)}"
                )
        except Exception as _curated_err:
            logging.getLogger("vector_plot").warning(f"Curated kinase→receptor fallback failed: {_curated_err}")

        # --- Source B-2: E3 Ligase → Receptor mapping (for ubiquitylation) ---
        # v9.40: For ubiquitylation orders, E3 ligases in kinase_names_set may not
        # map to receptors via Reactome. Use dedicated E3→Receptor DB as fallback.
        try:
            from app.services.ligand_receptor_db import get_receptors_for_e3_list
            unmapped_from_reactome = [
                k for k in kinase_names_set
                if not any(
                    k in (rec_info.get("via_kinases") or [])
                    for rec_info in reactome_receptors.values()
                )
            ]
            if unmapped_from_reactome:
                e3_receptor_map = get_receptors_for_e3_list(unmapped_from_reactome)
                for e3_name, receptors in e3_receptor_map.items():
                    for rec in receptors:
                        rec_name = rec["receptor"]
                        if rec_name not in reactome_receptors:
                            downstream_ptms = kinase_ptm_map.get(e3_name, set())
                            reactome_receptors[rec_name] = {
                                "name": rec_name,
                                "receptor_class": rec.get("receptor_class", ""),
                                "downstream_ptm_count": max(len(downstream_ptms), 1),
                                "downstream_ptms": sorted(downstream_ptms)[:10] if downstream_ptms else [],
                                "via_kinases": [e3_name],
                                "pathway": rec.get("pathway", ""),
                                "signaling_pathway": rec.get("pathway", ""),
                                "source": "e3_ligase_db",
                                "evidence": rec.get("evidence", ""),
                                "pmid": rec.get("pmid", ""),
                                "has_receptor_specific_db": True,
                            }
                        else:
                            existing = reactome_receptors[rec_name]
                            via = existing.get("via_kinases") or []
                            if e3_name not in via:
                                via.append(e3_name)
                                existing["via_kinases"] = via[:8]
                logging.getLogger("vector_plot").info(
                    f"E3 DB (Source B-2): Found {len(e3_receptor_map)} E3 ligases with receptor mappings "
                    f"from {len(unmapped_from_reactome)} unmapped candidates"
                )
        except Exception as _e3_err:
            logging.getLogger("vector_plot").warning(f"E3 receptor lookup failed: {_e3_err}")

        # --- Source B-3: UbiNet/E3Atlas enriched pathway context (v9.41) ---
        # Uses ubiquitylation_db_client for deeper E3→Receptor inference
        # with pathway context, biological process, and evidence levels.
        if ptm_type_str in ("ubiquitylation", "ubiquitination"):
            try:
                from app.services.ubiquitylation_db_client import (
                    get_ubiquitylation_db_client,
                )
                ubi_client = get_ubiquitylation_db_client()
                for e3_name in list(kinase_names_set):
                    ubi_receptors = ubi_client.infer_receptors_from_e3_local(e3_name)
                    for rec_info in ubi_receptors:
                        rec_name = rec_info["receptor"]
                        if rec_name not in reactome_receptors:
                            reactome_receptors[rec_name] = {
                                "name": rec_name,
                                "receptor_class": "ubiquitylation_pathway",
                                "via_kinases": [e3_name],
                                "pathway": rec_info.get("pathway", ""),
                                "source": "ubiquitylation_db_client",
                                "evidence": rec_info.get("evidence_level", "curated"),
                                "biological_process": rec_info.get("biological_process", ""),
                            }
                        else:
                            existing = reactome_receptors[rec_name]
                            via = existing.get("via_kinases") or []
                            if e3_name not in via:
                                via.append(e3_name)
                                existing["via_kinases"] = via[:8]
                            # Enrich with biological process if not present
                            if not existing.get("biological_process") and rec_info.get("biological_process"):
                                existing["biological_process"] = rec_info["biological_process"]
                logging.getLogger("vector_plot").info(
                    f"UbiNet/E3Atlas (Source B-3): enriched receptor context for "
                    f"{len(kinase_names_set)} E3 candidates"
                )
            except Exception as _ubi_err:
                logging.getLogger("vector_plot").debug(f"UbiNet enrichment skipped: {_ubi_err}")


        # --- Source C: Treatment-context-based receptor inference ---
        # Uses order.analysis_context.treatment to look up known ligand→receptor pairs.
        # UniProt fallback results are scored against the current PTM kinase set
        # and filtered to keep only biologically relevant receptors.
        treatment_receptors: dict = {}  # receptor_name -> {info}
        try:
            ctx = order.analysis_context or {}
            treatment_text = ctx.get("treatment", "") or ""
            if treatment_text.strip():
                from app.services.ligand_receptor_db import (
                    lookup_receptors_for_treatment,
                    score_uniprot_receptor,
                )
                matches = lookup_receptors_for_treatment(treatment_text)
                # Reactome receptor names for cross-validation bonus
                reactome_names: set[str] = set(reactome_receptors.keys())

                for rank, m in enumerate(matches):
                    rec_name = m["receptor_name"]
                    is_curated = m.get("source") == "treatment_context"  # internal DB
                    is_uniprot = m.get("source") == "treatment_context_uniprot"

                    # Score UniProt fallback results against active kinases
                    relevance_score = 0
                    if is_uniprot:
                        relevance_score = score_uniprot_receptor(
                            receptor_name=rec_name,
                            receptor_class=m["receptor_class"],
                            active_kinases=kinase_names_set,
                            reactome_receptor_names=reactome_names,
                            uniprot_rank=rank,
                        )
                        # Filter: skip if score is 0 (no kinase overlap, not in Reactome)
                        if relevance_score == 0:
                            logging.getLogger("vector_plot").debug(
                                f"Source C: Filtered out UniProt receptor '{rec_name}' "
                                f"(score=0, no kinase overlap with active set {sorted(kinase_names_set)[:5]})"
                            )
                            continue
                    else:
                        # Curated internal DB: always include, score = PTM count
                        relevance_score = len(top_n_ptms)

                    # v9.37: General receptor-specific kinase mapping
                    from app.services.ligand_receptor_db import (
                        _RECEPTOR_DOWNSTREAM_KINASES,
                    )

                    _CANONICAL_DOWNSTREAM: dict = {
                        "Integrin": ["PTK2", "FAK", "SRC", "ILK", "ROCK1", "ROCK2", "PAK1", "PAK2", "PAK4",
                                      "ITGB1BP1", "PXN", "VCL", "TLN1", "PARVA", "FERMT2",
                                      "CDC42", "RAC1", "RHOA", "LIMK1", "LIMK2", "CFL1",
                                      "PI3K", "PIK3CA", "PIK3R1", "AKT1", "AKT2",
                                      "MAPK1", "MAPK3", "ERK1", "ERK2", "MAP2K1", "MAP2K2",
                                      "BCAR1", "CRK", "CRKL", "DOCK1"],
                        "RTK": ["GRB2", "SOS1", "RAS", "RAF1", "BRAF", "MAP2K1", "MAP2K2",
                                 "MAPK1", "MAPK3", "ERK1", "ERK2",
                                 "PI3K", "PIK3CA", "AKT1", "AKT2", "MTOR",
                                 "SRC", "JAK1", "JAK2", "STAT3", "STAT5A",
                                 "PLCγ", "PLCG1", "PKC", "PRKCA", "PRKCB"],
                        "GPCR": ["ADCY", "PKA", "PRKACA", "PRKACB", "PRKAR1A",
                                  "PLCB1", "PLCB3", "PKC", "PRKCA", "PRKCB",
                                  "GRK2", "GRK3", "GRK5", "GRK6",
                                  "ROCK1", "ROCK2", "RHOA",
                                  "PI3K", "PIK3CA", "AKT1", "MAPK1", "MAPK3",
                                  "ARRB1", "ARRB2"],
                        "Receptor": ["SRC", "MAPK1", "MAPK3", "AKT1", "PI3K", "JAK1", "JAK2"],
                    }
                    rec_class = m["receptor_class"]
                    canonical_list = _CANONICAL_DOWNSTREAM.get(rec_class, _CANONICAL_DOWNSTREAM["Receptor"])

                    # Step 0: Receptor name normalization
                    _rec_aliases: list[str] = []
                    _base_name = rec_name.split("(")[0].strip()
                    _rec_aliases.append(_base_name.upper())
                    if "(" in rec_name:
                        _alias = rec_name.split("(")[1].replace(")", "").strip()
                        if _alias:
                            _rec_aliases.append(_alias.upper())
                    for _a in list(_rec_aliases):
                        _clean = _a.replace("-", "").replace(" ", "")
                        if _clean != _a:
                            _rec_aliases.append(_clean)

                    # Step 1: Receptor-specific kinases from curated DB
                    receptor_specific_kinases: set = set()
                    for _alias in _rec_aliases:
                        if _alias in _RECEPTOR_DOWNSTREAM_KINASES:
                            receptor_specific_kinases.update(
                                _RECEPTOR_DOWNSTREAM_KINASES[_alias]
                            )
                    has_receptor_specific = len(receptor_specific_kinases) > 0

                    # Step 2: Build via_kinases with 3-tier priority
                    detected_via_kinases: list[str] = []
                    _seen_via: set = set()

                    def _add_kinase(k: str):
                        if k not in _seen_via:
                            _seen_via.add(k)
                            detected_via_kinases.append(k)

                    # Priority 1: Receptor-specific kinases
                    if has_receptor_specific:
                        for k in receptor_specific_kinases:
                            if k in kinase_names_set:
                                _add_kinase(k)

                    # Priority 2: Canonical class-level kinases
                    for k in canonical_list:
                        if k in kinase_names_set:
                            _add_kinase(k)

                    # Priority 3: Supplementary kinases (only if receptor-specific DB exists)
                    downstream_ptm_set = set(p["label"] for p in top_n_ptms)
                    if has_receptor_specific:
                        for kname, kptms in kinase_ptm_map.items():
                            if kname not in _seen_via and kptms & downstream_ptm_set:
                                if kname in receptor_specific_kinases:
                                    _add_kinase(kname)

                    unique_via_kinases = detected_via_kinases[:8]

                    # Step 3: Recalculate downstream_ptm_count
                    all_downstream_ptms: set = set()
                    for k in unique_via_kinases:
                        all_downstream_ptms |= kinase_ptm_map.get(k, set())
                    if not all_downstream_ptms:
                        all_downstream_ptms = downstream_ptm_set
                    actual_downstream_count = len(all_downstream_ptms) if all_downstream_ptms else relevance_score

                    treatment_receptors[rec_name] = {
                        "name": rec_name,
                        "receptor_class": rec_class,
                        "downstream_ptm_count": actual_downstream_count,
                        "downstream_ptms": sorted(all_downstream_ptms)[:10] if all_downstream_ptms else [p["label"] for p in top_n_ptms[:10]],
                        "via_kinases": unique_via_kinases,
                        "pathway": m.get("pathway", ""),
                        "evidence": m.get("evidence", ""),
                        "matched_ligand": m.get("ligand", ""),
                        "source": m.get("source", "treatment_context"),
                        "relevance_score": actual_downstream_count,
                        "has_receptor_specific_db": has_receptor_specific,
                    }

                if treatment_receptors:
                    logging.getLogger("vector_plot").info(
                        f"Source C: Kept {len(treatment_receptors)}/{len(matches)} receptor(s) "
                        f"for treatment '{treatment_text}' after kinase-activity scoring"
                    )
        except Exception as e:
            logging.getLogger("vector_plot").warning(f"Treatment-context receptor lookup failed: {e}")

        # v9.37: Reverse-infer via_kinases for Source A literature receptors
        # (must run after Source B where kinase_names_set is populated)
        if literature_receptors and kinase_names_set:
            for _lit_rec_name, _lit_info in literature_receptors.items():
                _a_aliases: list[str] = [_lit_rec_name.split("(")[0].strip().upper()]
                if "(" in _lit_rec_name:
                    _a_alias = _lit_rec_name.split("(")[1].replace(")", "").strip().upper()
                    if _a_alias:
                        _a_aliases.append(_a_alias)
                for _aa in list(_a_aliases):
                    _ac = _aa.replace("-", "").replace(" ", "")
                    if _ac != _aa:
                        _a_aliases.append(_ac)

                _a_rec_specific: set = set()
                for _aa in _a_aliases:
                    if _aa in _RECEPTOR_DOWNSTREAM_KINASES:
                        _a_rec_specific.update(_RECEPTOR_DOWNSTREAM_KINASES[_aa])

                _a_has_specific = len(_a_rec_specific) > 0
                _lit_info["has_receptor_specific_db"] = _a_has_specific
                if _a_has_specific:
                    _lit_info["via_kinases"] = [k for k in _a_rec_specific if k in kinase_names_set][:8]

        # --- Merge all three sources (C > B > A priority) ---
        merged: dict = {}
        # Source C first (treatment context — most directly relevant)
        for rec_name, info in treatment_receptors.items():
            merged[rec_name] = info
        # Source B (Reactome pathway inference)
        for rec_name, info in reactome_receptors.items():
            if rec_name not in merged:
                merged[rec_name] = info
            else:
                # Supplement with Reactome kinase info
                existing = merged[rec_name]
                if not existing.get("via_kinases") and info.get("via_kinases"):
                    existing["via_kinases"] = info["via_kinases"]
                if not existing.get("signaling_pathway") and info.get("signaling_pathway"):
                    existing["signaling_pathway"] = info["signaling_pathway"]
        # Source A (literature — least reliable)
        for rec_name, info in literature_receptors.items():
            if rec_name not in merged:
                merged[rec_name] = info
            else:
                # Supplement with literature PTM count
                existing = merged[rec_name]
                lit_ptms = set(info.get("downstream_ptms", []))
                existing_ptms = set(existing.get("downstream_ptms", []))
                combined = existing_ptms | lit_ptms
                existing["downstream_ptm_count"] = max(existing["downstream_ptm_count"], len(combined))
                existing["downstream_ptms"] = sorted(combined)[:10]

        # ── v9.37: General Uniqueness Score, Grouping, and Unique PTM Metadata ──
        from collections import defaultdict
        _all_kinase_freq: dict = defaultdict(int)
        for _ri in merged.values():
            for _k in _ri.get("via_kinases", []):
                _all_kinase_freq[_k] += 1

        for _ri in merged.values():
            _vk = _ri.get("via_kinases", [])
            if not _vk:
                _ri["uniqueness_score"] = 0.0
                _ri["unique_kinases"] = []
                _ri["shared_kinases"] = []
                continue
            _unique_k = []
            _shared_k = []
            _u_sum = 0.0
            for _k in _vk:
                _freq = _all_kinase_freq.get(_k, 1)
                _u_sum += 1.0 / _freq
                if _freq == 1:
                    _unique_k.append(_k)
                else:
                    _shared_k.append(_k)
            _ri["uniqueness_score"] = round(_u_sum / len(_vk), 3)
            _ri["unique_kinases"] = _unique_k
            _ri["shared_kinases"] = _shared_k

        # --- Grouping: receptors with identical via_kinases sets ---
        _sig_to_members: dict = defaultdict(list)
        for _ri in merged.values():
            _sig = frozenset(_ri.get("via_kinases", []))
            _sig_to_members[_sig].append(_ri["name"])

        _group_counter = 0
        _sig_to_gid: dict = {}
        for _sig, _members in _sig_to_members.items():
            if len(_members) > 1:
                _group_counter += 1
                _sig_to_gid[_sig] = f"kinase_group_{_group_counter}"

        for _ri in merged.values():
            _sig = frozenset(_ri.get("via_kinases", []))
            if _sig in _sig_to_gid:
                _ri["kinase_group_id"] = _sig_to_gid[_sig]
                _ri["kinase_group_members"] = _sig_to_members[_sig]
            else:
                _ri["kinase_group_id"] = None
                _ri["kinase_group_members"] = [_ri["name"]]

        # --- Unique PTM Subset ---
        _all_ptm_freq: dict = defaultdict(int)
        for _ri in merged.values():
            for _p in _ri.get("downstream_ptms", []):
                _all_ptm_freq[_p] += 1

        for _ri in merged.values():
            _ptms = _ri.get("downstream_ptms", [])
            _ri["unique_ptms"] = [p for p in _ptms if _all_ptm_freq[p] == 1]
            _ri["shared_ptms"] = [p for p in _ptms if _all_ptm_freq[p] > 1]
            _ri["unique_ptm_ratio"] = round(
                len(_ri["unique_ptms"]) / max(len(_ptms), 1), 3
            )

        _uq_summary = ", ".join(
            f"{r['name']}={r.get('uniqueness_score', 0):.2f}" for r in merged.values()
        )
        logging.getLogger("vector_plot").info(
            f"Receptor grouping: {_group_counter} groups from {len(merged)} receptors. "
            f"Uniqueness scores: {_uq_summary}"
        )

        # ══════════════════════════════════════════════════════════════════════
        # v9.42: Co-Wave Divergence Receptor Inference
        # ══════════════════════════════════════════════════════════════════════
        # Hub kinases that appear in almost every RTK pathway — penalize them
        _HUB_KINASES = {"AKT1", "AKT2", "MAPK1", "MAPK3", "PI3K", "SRC",
                        "ERK1", "ERK2", "PIK3CA", "PIK3R1"}
        _HUB_PENALTY = 0.2  # weight multiplier for hub kinases

        # Determine if multi-time-point data is available
        _sample_cfg = order.sample_config or {}
        _is_single_tp = _sample_cfg.get("single_time_point", False)
        _conditions_in_data = sorted(set(
            r["condition"] for r in vector_data if r.get("condition")
        ))
        _is_multi_tp = (not _is_single_tp) and len(_conditions_in_data) >= 3

        _cowave_analysis = None

        if _is_multi_tp and top_n_ptms:
            # ── Parse time order from condition labels ──
            import re as _cw_re
            def _parse_time_minutes(cond_str: str) -> float:
                """Parse condition string to minutes for ordering."""
                m = _cw_re.match(r'^([\d.]+)\s*(min|m|h|hr|hour|d|day)s?$', cond_str.strip(), _cw_re.IGNORECASE)
                if m:
                    val = float(m.group(1))
                    unit = m.group(2).lower()
                    if unit in ('h', 'hr', 'hour'):
                        return val * 60
                    elif unit in ('d', 'day'):
                        return val * 1440
                    return val  # minutes
                # Try just numeric
                m2 = _cw_re.match(r'^([\d.]+)$', cond_str.strip())
                if m2:
                    return float(m2.group(1))
                return float('inf')  # unparseable → sort last

            _cond_order = sorted(_conditions_in_data, key=_parse_time_minutes)
            _parseable = [c for c in _cond_order if _parse_time_minutes(c) != float('inf')]
            _is_multi_tp = len(_parseable) >= 3  # re-check after parsing

        if _is_multi_tp and top_n_ptms:
            # ── Build PTM × Time matrix ──
            _ptm_labels_set = set(p["label"] for p in top_n_ptms)
            _ptm_time_matrix: dict = {}  # ptm_label → {cond: fc}
            for r in vector_data:
                _lbl = f"{r['gene']} {r['position']}".strip()
                if _lbl in _ptm_labels_set:
                    if _lbl not in _ptm_time_matrix:
                        _ptm_time_matrix[_lbl] = {}
                    _ptm_time_matrix[_lbl][r["condition"]] = r["ptm_relative_log2fc"]

            # Only proceed if enough PTMs have full time-series
            _full_ts_ptms = [
                lbl for lbl, conds in _ptm_time_matrix.items()
                if len([c for c in _parseable if c in conds]) >= 3
            ]

            if len(_full_ts_ptms) >= 5:
                # ── Compute pairwise Pearson correlation ──
                import math as _cw_math
                _vectors: dict = {}  # ptm_label → list of FC values (ordered by time)
                for lbl in _full_ts_ptms:
                    _vectors[lbl] = [_ptm_time_matrix[lbl].get(c, 0.0) for c in _parseable]

                def _pearson(v1: list, v2: list) -> float:
                    n = len(v1)
                    if n < 3:
                        return 0.0
                    m1 = sum(v1) / n
                    m2 = sum(v2) / n
                    num = sum((a - m1) * (b - m2) for a, b in zip(v1, v2))
                    d1 = _cw_math.sqrt(sum((a - m1) ** 2 for a in v1))
                    d2 = _cw_math.sqrt(sum((b - m2) ** 2 for b in v2))
                    if d1 == 0 or d2 == 0:
                        return 0.0
                    return num / (d1 * d2)

                # ── Simple greedy clustering (correlation threshold) ──
                _CW_THRESHOLD = 0.7
                _labels_list = list(_vectors.keys())
                _assigned = [False] * len(_labels_list)
                _clusters: list[list[str]] = []

                for i in range(len(_labels_list)):
                    if _assigned[i]:
                        continue
                    cluster = [_labels_list[i]]
                    _assigned[i] = True
                    for j in range(i + 1, len(_labels_list)):
                        if _assigned[j]:
                            continue
                        corr = _pearson(_vectors[_labels_list[i]], _vectors[_labels_list[j]])
                        if corr >= _CW_THRESHOLD:
                            cluster.append(_labels_list[j])
                            _assigned[j] = True
                    _clusters.append(cluster)

                # ── Determine cluster-specific vs shared kinases ──
                _cluster_kinases: list[set] = []  # per cluster
                for cl in _clusters:
                    _cl_kinases: set = set()
                    for ptm_lbl in cl:
                        for kin_name, kin_ptms in kinase_ptm_map.items():
                            if ptm_lbl in kin_ptms:
                                _cl_kinases.add(kin_name)
                    _cluster_kinases.append(_cl_kinases)

                # Count how many clusters each kinase appears in
                _kinase_cluster_freq: dict = defaultdict(int)
                for _cl_kins in _cluster_kinases:
                    for k in _cl_kins:
                        _kinase_cluster_freq[k] += 1

                # ── v9.44: Compute co-wave receptor score with kinase module confidence ──
                # For each receptor: score = Σ (cluster_specificity × hub_weight × ptm_coverage × module_confidence)
                # Kinases whose modules have high co-wave coherence get priority
                for _ri in merged.values():
                    _vk = _ri.get("via_kinases", [])
                    if not _vk:
                        _ri["cowave_score"] = 0.0
                        continue
                    _cw_score = 0.0
                    for k in _vk:
                        # Hub penalty
                        _hub_w = _HUB_PENALTY if k in _HUB_KINASES else 1.0
                        # Cluster specificity: 1/N where N = number of clusters this kinase appears in
                        _cl_freq = _kinase_cluster_freq.get(k, 1)
                        _spec_w = 1.0 / max(_cl_freq, 1)
                        # PTM coverage: how many top_n PTMs this kinase covers
                        _ptm_cov = len(kinase_ptm_map.get(k, set()) & _ptm_labels_set)
                        # v9.44: Co-wave coherence boost — kinases concentrated in few clusters
                        # get amplified score (temporally specific = more reliable pathway)
                        _module_boost = 1.0
                        # Use kinase_ptm_map to find which co-wave clusters this kinase's PTMs belong to
                        _kinase_ptm_set = kinase_ptm_map.get(k, set())
                        _kinase_in_clusters = set()
                        for _cl_idx, _cl_ptms in enumerate(_clusters):
                            if _kinase_ptm_set & set(_cl_ptms):
                                _kinase_in_clusters.add(_cl_idx)
                        # Coherence: if kinase's PTMs are concentrated in 1-2 clusters (not spread)
                        if len(_kinase_in_clusters) <= 2 and len(_kinase_ptm_set) >= 3:
                            _module_boost = 1.5  # 50% boost for temporally coherent kinases
                        elif len(_kinase_in_clusters) == 1 and len(_kinase_ptm_set) >= 2:
                            _module_boost = 1.8  # 80% boost for single-cluster kinases

                        _cw_score += _hub_w * _spec_w * max(_ptm_cov, 1) * _module_boost
                    _ri["cowave_score"] = round(_cw_score, 3)

                # ── Detect temporal patterns per cluster ──
                _cluster_patterns: list[dict] = []
                for idx, cl in enumerate(_clusters):
                    # Average FC per time point for this cluster
                    _avg_fc = []
                    for c in _parseable:
                        vals = [_ptm_time_matrix[lbl].get(c, 0.0) for lbl in cl if lbl in _ptm_time_matrix]
                        _avg_fc.append(sum(vals) / max(len(vals), 1))
                    # Classify pattern
                    if len(_avg_fc) >= 3:
                        _early = abs(_avg_fc[0])
                        _late = abs(_avg_fc[-1])
                        _mid = abs(_avg_fc[len(_avg_fc) // 2])
                        if _early > _late and _early > _mid:
                            _pattern = "early_transient"
                        elif _late > _early and _late > _mid:
                            _pattern = "late_onset"
                        elif _mid > _early and _mid > _late:
                            _pattern = "mid_peak"
                        elif _early > 0 and _late > 0 and abs(_early - _late) / max(_early, _late) < 0.3:
                            _pattern = "sustained"
                        else:
                            _pattern = "variable"
                    else:
                        _pattern = "unknown"

                    # Specific kinases for this cluster
                    _cl_specific = [
                        k for k in _cluster_kinases[idx]
                        if _kinase_cluster_freq[k] == 1 and k not in _HUB_KINASES
                    ]
                    _cl_hub = [k for k in _cluster_kinases[idx] if k in _HUB_KINASES]

                    _cluster_patterns.append({
                        "cluster_id": idx + 1,
                        "ptm_labels": cl[:15],  # limit for storage
                        "ptm_count": len(cl),
                        "specific_kinases": _cl_specific[:8],
                        "hub_kinases": _cl_hub[:5],
                        "temporal_pattern": _pattern,
                        "avg_fc_timeseries": [round(v, 3) for v in _avg_fc],
                    })

                _cowave_analysis = {
                    "is_multi_timepoint": True,
                    "conditions_ordered": _parseable,
                    "num_clusters": len(_clusters),
                    "clusters": _cluster_patterns,
                    "scoring_method": "cowave_divergence",
                }

                logging.getLogger("vector_plot").info(
                    f"Co-wave analysis: {len(_clusters)} clusters from {len(_full_ts_ptms)} PTMs, "
                    f"conditions={_parseable}"
                )
            else:
                # Not enough PTMs with full time-series → fallback
                _is_multi_tp = False

        # ── Fallback scoring for single-time-point or insufficient data ──
        if not _is_multi_tp or _cowave_analysis is None:
            # Method A+B: Hub-penalized uniqueness scoring
            for _ri in merged.values():
                _vk = _ri.get("via_kinases", [])
                if not _vk:
                    _ri["cowave_score"] = 0.0
                    continue
                _fb_score = 0.0
                for k in _vk:
                    _hub_w = _HUB_PENALTY if k in _HUB_KINASES else 1.0
                    _freq = _all_kinase_freq.get(k, 1)
                    _uniqueness_w = 1.0 / _freq
                    _ptm_cov = len(kinase_ptm_map.get(k, set()))
                    _fb_score += _hub_w * _uniqueness_w * max(_ptm_cov, 1)
                _ri["cowave_score"] = round(_fb_score, 3)

            _cowave_analysis = {
                "is_multi_timepoint": False,
                "scoring_method": "hub_penalized_uniqueness",
            }

        # ══════════════════════════════════════════════════════════════════════
        # v10.2: Combined Confidence Score + Hard Filter
        # ══════════════════════════════════════════════════════════════════════
        # Source reliability mapping
        _SOURCE_RELIABILITY = {
            "treatment_context": 1.0,
            "treatment_context_uniprot": 0.7,
            "curated_kinase_receptor_db": 0.8,
            "reactome": 0.6,
            "e3_ligase_db": 0.7,
            "ubiquitylation_db_client": 0.6,
            "literature": 0.3,
        }

        # Normalize cowave_score for confidence calculation
        _all_cowave_scores = [r.get("cowave_score", 0) for r in merged.values()]
        _max_cowave = max(_all_cowave_scores) if _all_cowave_scores else 1.0
        if _max_cowave == 0:
            _max_cowave = 1.0

        # Calculate confidence score for each receptor
        for _ri in merged.values():
            _vk = _ri.get("via_kinases", [])
            _n_kinases = len(_vk)

            # Component 1: Normalized cowave score (0~1)
            _norm_cowave = _ri.get("cowave_score", 0) / _max_cowave

            # Component 2: Convergence score — how many kinases point to this receptor
            # Normalized: 1 kinase=0.2, 2=0.5, 3=0.7, 4+=0.9, 5+=1.0
            _convergence = min(_n_kinases / 5.0, 1.0) if _n_kinases > 0 else 0.0

            # Component 3: Source reliability
            _source = _ri.get("source", "literature")
            _source_rel = _SOURCE_RELIABILITY.get(_source, 0.3)

            # Component 4: Unique PTM ratio (already calculated)
            _upr = _ri.get("unique_ptm_ratio", 0.0)

            # Component 5: Has receptor-specific curated DB
            _has_db = 1.0 if _ri.get("has_receptor_specific_db") else 0.0

            # Combined confidence score
            _confidence = (
                0.35 * _norm_cowave +
                0.25 * _convergence +
                0.20 * _source_rel +
                0.10 * _upr +
                0.10 * _has_db
            )
            _ri["confidence_score"] = round(_confidence, 4)

        # ── Hard Filter ──
        # Rule 1: via_kinases < 2 AND source != treatment_context → remove
        # Rule 2: kinase_group_id exists → keep only the one with highest confidence in group
        _filtered_merged: dict = {}
        _group_best: dict = {}  # group_id → best receptor name

        for _rn, _ri in merged.items():
            _vk = _ri.get("via_kinases", [])
            _source = _ri.get("source", "")

            # Hard filter: single kinase AND not treatment context → skip
            if len(_vk) < 2 and _source not in ("treatment_context", "treatment_context_uniprot"):
                logging.getLogger("vector_plot").debug(
                    f"Receptor '{_rn}' filtered: via_kinases={len(_vk)}, source={_source}"
                )
                continue

            # Group dedup: keep best per kinase_group
            _gid = _ri.get("kinase_group_id")
            if _gid:
                if _gid not in _group_best:
                    _group_best[_gid] = (_rn, _ri["confidence_score"])
                    _filtered_merged[_rn] = _ri
                else:
                    _prev_name, _prev_score = _group_best[_gid]
                    if _ri["confidence_score"] > _prev_score:
                        # Replace previous with current
                        _filtered_merged.pop(_prev_name, None)
                        _filtered_merged[_rn] = _ri
                        _group_best[_gid] = (_rn, _ri["confidence_score"])
                    # else: skip this one (lower score in same group)
            else:
                _filtered_merged[_rn] = _ri

        # ── Soft Threshold: confidence >= 0.3 ──
        _CONFIDENCE_THRESHOLD = 0.3
        _above_threshold = {
            rn: ri for rn, ri in _filtered_merged.items()
            if ri["confidence_score"] >= _CONFIDENCE_THRESHOLD
        }

        # Safety: always keep at least top 5 if threshold is too aggressive
        if len(_above_threshold) < 5 and len(_filtered_merged) >= 5:
            _sorted_filtered = sorted(
                _filtered_merged.values(),
                key=lambda x: x["confidence_score"],
                reverse=True,
            )
            _above_threshold = {r["name"]: r for r in _sorted_filtered[:5]}

        # Also always keep treatment_context receptors regardless of threshold
        for _rn, _ri in _filtered_merged.items():
            if _ri.get("source") in ("treatment_context", "treatment_context_uniprot"):
                _above_threshold[_rn] = _ri

        logging.getLogger("vector_plot").info(
            f"Receptor confidence filter: {len(merged)} raw → "
            f"{len(_filtered_merged)} after hard filter → "
            f"{len(_above_threshold)} after threshold ({_CONFIDENCE_THRESHOLD})"
        )

        # ── Final sorting: confidence_score primary, cowave_score secondary ──
        inferred_receptors = sorted(
            _above_threshold.values(),
            key=lambda x: (x.get("confidence_score", 0), x.get("cowave_score", 0)),
            reverse=True,
        )

        # v9.20: Persist receptor inference to DB so report_generation can use it
        try:
            order.receptor_inference_data = {
                "receptors": inferred_receptors,
                "top_n_setting": top_n_setting,
                "locked": lock_receptor,
                "cowave_analysis": _cowave_analysis,
                "saved_at": __import__('datetime').datetime.utcnow().isoformat(),
            }
            await db.commit()
            logging.getLogger("vector_plot").info(
                f"Saved {len(inferred_receptors)} inferred receptors to DB for order {order.id}"
            )
        except Exception as _save_err:
            logging.getLogger("vector_plot").warning(
                f"Failed to save receptor_inference_data to DB: {_save_err}"
            )

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
        "inferred_receptors": inferred_receptors,  # v9.18
        "cowave_analysis": _cowave_analysis if '_cowave_analysis' in locals() else None,  # v9.42
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
    await _check_order_access_async(order, user, db)

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
    await _check_order_access_async(order, user, db)

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
    await _check_order_access_async(order, user, db)

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
    await _require_write_access(order, user, db)

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
    await _check_order_access_async(order, user, db)

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
# v10.7: Ubiquitin Chain Linkage Analysis
# ---------------------------------------------------------------------------

@router.get("/{order_id}/ubiquitin-linkage")
async def get_ubiquitin_linkage(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Return ubiquitin chain linkage ratio analysis (temporal)."""
    import json as _json
    from app.config import get_settings
    settings = get_settings()

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    await _check_order_access_async(order, user, db)

    if order.ptm_type != "ubiquitylation":
        return {"detected": False, "message": "Linkage analysis only available for ubiquitylation orders"}

    output_dir = Path(settings.OUTPUT_DIR) / order.order_code
    if not output_dir.exists():
        return {"detected": False, "message": "Output directory not found"}

    file_suffix = "_ubi"
    linkage_file = output_dir / f"ubiquitin_linkage_analysis{file_suffix}.json"
    if not linkage_file.exists():
        return {"detected": False, "message": "Linkage analysis not yet computed"}

    try:
        with open(linkage_file, "r", encoding="utf-8") as f:
            data = _json.load(f)
        return data
    except Exception as e:
        return {"detected": False, "message": f"Error loading linkage data: {str(e)}"}


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
    await _check_order_access_async(order, user, db)

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
    await _require_write_access(order, user, db)

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
    await _require_write_access(order, user, db)

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
        # SCF complex degrons (phosphodegron-based)
        "SCF_FBXW7": r"[LI]...[ST]P..[ST]",       # Cyclin E, c-Myc, c-Jun phosphodegron
        "SCF_BTRC": r"DS[GA][ILVM][ST]",            # IkB, beta-catenin phosphodegron
        "SCF_SKP2": r"[RK]..[ILVM]..[ST]P",        # p27, p21 phosphodegron
        "SCF_FBXO4": r"[DE].{0,2}[ST].[DE]",       # Cyclin D1
        "SCF_FBXO31": r"[DE].{1,3}[ST].[DE]",      # CDH1
        "SCF_complex": r"[DE].{0,2}[ST].[DE]",     # generic SCF degron
        # APC/C degrons
        "APC/C_D-box": r"R..L.{2,4}[ILVM]",        # D-box: RXXL
        "APC/C_KEN-box": r"KEN",                    # KEN-box
        "APC/C_ABBA": r"[FY]..[FY].{3,5}[FY]",     # ABBA motif
        # CRL2/VHL
        "VHL": r"LA.{1,2}[ILVM]P",                 # HIF-1alpha
        # MDM2
        "MDM2": r"F..W..L",                         # p53 MDM2-binding
        # NEDD4 family (HECT)
        "NEDD4L": r"[LP]P.Y",                       # PY motif (PPXY)
        "NEDD4/ITCH": r"[LP]P.Y",
        "WWP1/2": r"[LP]P.Y",
        "SMURF1/2": r"[LP]P.Y",
        # CHIP/STUB1
        "CHIP/STUB1": r"[ILVM].{1,2}[ILVM]",       # hydrophobic patch (misfolded proteins)
        # TRAF family
        "TRAF6": r"P.E..[AQEG]",                    # TRAF6 binding motif
        "TRAF2/5": r"P.Q.T",                        # TRAF2/5 binding motif
        # KEAP1/CUL3
        "KEAP1/CUL3": r"[DE][ST]GE",               # NRF2 ETGE/DLG motif
        "KEAP1_DLG": r"DLG.{1,3}[DE]",             # NRF2 DLG motif
        # SPOP/CUL3
        "SPOP": r"[ST].{0,2}[ST].{0,2}[ST]",       # SPOP SBC degron
        # PARKIN (RBR)
        "PARKIN": r"[ILVM].{2,4}[KR].{2,4}[ILVM]", # mitochondrial substrates
        # TRIM family
        "TRIM25": r"[DE].{2,4}[DE]",               # TRIM25 substrates
        "TRIM21": r"[FY].{1,3}[FY]",               # TRIM21 substrates
        "TRIM32": r"[ILVM].{3,5}[ILVM]",           # TRIM32 substrates
        # HUWE1/MULE
        "HUWE1": r"[DE].{3,6}[DE]",                # HUWE1 acidic degron
        # CBL (RING)
        "CBL": r"[FY].{1,2}[FY].{1,2}[FY]",       # CBL pTyr recognition
        # p62/SQSTM1 (autophagy receptor)
        "p62/SQSTM1": r"[ILVM].{1,3}[ILVM].{1,3}[ILVM]",  # LIR motif region
        # Generic phosphodegron
        "phosphodegron": r"[ST]P.{1,3}[ST]P",      # proline-directed phosphodegron
    }
    motif_db = phospho_motif_db if order.ptm_type == "phosphorylation" else ubi_motif_db

    # ── Residue-based kinase/E3 family prediction (fallback when no sequence) ──
    is_ubi_order = order.ptm_type == "ubiquitylation"
    if is_ubi_order:
        residue_kinase_families = {
            # Ubiquitylation always occurs on K (Lysine)
            "K": ["SCF_complex", "APC/C", "MDM2", "NEDD4", "CHIP/STUB1",
                  "TRAF6", "PARKIN", "TRIM25", "VHL", "KEAP1/CUL3"],
        }
    else:
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
                # ── Source 2b: e3_substrate (ubiquitylation-specific) ──
                for e3pair in reg.get("e3_substrate", []):
                    if isinstance(e3pair, dict) and e3pair.get("e3_ligase"):
                        known_kinases.append({
                            "kinase": e3pair["e3_ligase"],
                            "confidence": "literature",
                            "mechanism": f"E3 ligase → substrate: {e3pair.get('substrate', '')} ({e3pair.get('context', '')})",
                            "source": "e3_substrate_pair",
                        })
                # ── Source 2c: dub_substrate (ubiquitylation-specific) ──
                for dubpair in reg.get("dub_substrate", []):
                    if isinstance(dubpair, dict) and dubpair.get("dub"):
                        known_kinases.append({
                            "kinase": dubpair["dub"],
                            "confidence": "literature",
                            "mechanism": f"DUB → substrate: {dubpair.get('substrate', '')} ({dubpair.get('context', '')})",
                            "source": "dub_substrate_pair",
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

            # ── Source 4: fulltext_analysis → key_findings (kinase/E3 mentions) ──
            ft = rag.get("fulltext_analysis", {})
            if isinstance(ft, dict):
                is_ubi_mode = order.ptm_type == "ubiquitylation"
                if is_ubi_mode:
                    kinase_pattern = re.compile(
                        r'(?:ubiquitylated\s+by|ubiquitinated\s+by|substrate\s+of|target\s+of'
                        r'|ubiquitylates?|ubiquitinates?|E3\s+ligase\s+(?:for|of)'
                        r'|targets?\s+for\s+(?:proteasomal\s+)?degradation\s+by'
                        r'|mediated\s+by|regulated\s+by)'
                        r'\s+([A-Z][A-Za-z0-9]{1,15}(?:\s+(?:ligase|E3|RING|HECT|RBR))?)',
                        re.IGNORECASE,
                    )
                else:
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
                # ── Source 5b: abstract_analysis E3 ligase fields (ubiquitylation) ──
                for key_name in ("e3_ligases", "ubiquitin_ligases", "ligases", "e3_ligase",
                                 "upstream_e3", "predicted_e3", "dubs", "deubiquitylases"):
                    for item in aa.get(key_name, []):
                        if isinstance(item, str) and item:
                            known_kinases.append({
                                "kinase": item, "confidence": "predicted",
                                "mechanism": "", "source": "abstract_e3",
                            })
                        elif isinstance(item, dict) and (item.get("name") or item.get("e3") or item.get("ligase")):
                            known_kinases.append({
                                "kinase": item.get("name") or item.get("e3") or item.get("ligase"),
                                "confidence": item.get("confidence", "predicted"),
                                "mechanism": item.get("evidence", item.get("mechanism", "")),
                                "source": "abstract_e3",
                            })

            # ── Source 6: string_interactions (protein-protein interactions) ──
            # STRING DB interactions may include kinases/E3 ligases
            # Prefer string_db.interactions (dict list); fallback: parse string_interactions str list
            _s6_sdb = rag.get("string_db", {})
            _s6_sdb_ints = _s6_sdb.get("interactions", []) if isinstance(_s6_sdb, dict) else []
            if _s6_sdb_ints:
                string_ints = _s6_sdb_ints
            else:
                import re as _re_s6
                string_ints = []
                for _s in (rag.get("string_interactions", []) or []):
                    if isinstance(_s, dict):
                        string_ints.append(_s)
                    elif isinstance(_s, str):
                        _m = _re_s6.match(r"^(.+)\(([0-9.]+)\)$", _s.strip())
                        if _m:
                            string_ints.append({"partner": _m.group(1), "score": float(_m.group(2))})
            if string_ints:
                if order.ptm_type == "ubiquitylation":
                    kinase_keywords = {
                        "ligase", "ubiquitin", "RING", "HECT", "RBR",
                        "NEDD4", "TRIM", "RNF", "MDM2", "FBXW", "FBXO", "BTRC", "SKP",
                        "CUL", "VHL", "CHIP", "STUB", "PARKIN", "PRKN", "HUWE", "HERC",
                        "UBR", "MARCH", "ZNRF", "SMURF", "WWP", "ITCH", "NDFIP",
                        "SPOP", "KEAP", "BIRC", "XIAP", "TRAF", "HACE", "CBL",
                        "USP", "UCH", "OTU", "JAMM", "MINDY", "ZUFSP",  # DUBs
                        "deubiquityl", "deubiquitin",
                    }
                else:
                    kinase_keywords = {"kinase", "phosphotransferase", "CK1", "CK2", "CDK", "MAPK",
                                       "PKA", "PKC", "GSK", "AKT", "mTOR", "ATM", "ATR", "PLK",
                                       "AURK", "NEK", "DYRK", "CLK", "SRPK", "CAMK", "AMPK"}
                for si in string_ints:
                    partner = si.get("preferredName_B") or si.get("partner") or si.get("name", "")
                    score = si.get("score", 0)
                    if isinstance(score, float) and score <= 1.0:
                        score = score * 1000
                    if partner and score >= 700:  # High confidence STRING interaction
                        partner_upper = partner.upper()
                        if any(kw.upper() in partner_upper for kw in kinase_keywords):
                            known_kinases.append({
                                "kinase": partner,
                                "confidence": f"STRING (score={score:.0f})",
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
    await _require_write_access(order, user, db)

    ptms = body.get("ptms", [])
    cowave_modules_input = body.get("cowave_modules", [])
    force_refresh = body.get("force_refresh", False)

    if not ptms:
        raise HTTPException(status_code=400, detail="ptms list is required")

    # ── v9.44: Cache check ───────────────────────────────────────────────────────
    # Return cached result if available and input hasn't changed
    import hashlib as _hashlib
    _ptm_keys_sorted = sorted(f"{p.get('gene','').upper()}_{p.get('position','')}" for p in ptms)
    _cowave_keys_sorted = sorted(
        f"{cw.get('id',0)}:{','.join(sorted(cw.get('ptm_keys',[])))}"
        for cw in cowave_modules_input
    ) if cowave_modules_input else []
    _cache_input_str = f"{len(ptms)}|{'|'.join(_ptm_keys_sorted[:50])}|{'|'.join(_cowave_keys_sorted[:20])}"
    _cache_hash = _hashlib.md5(_cache_input_str.encode()).hexdigest()[:12]

    # _cache_probe: frontend mount-time check — return any existing cache regardless of hash
    _cache_probe = body.get("_cache_probe", False)

    if not force_refresh and order.kinase_analysis_data:
        _cached = order.kinase_analysis_data
        # v9.48.1: Handle case where kinase_analysis_data is stored as string (double-serialized)
        if isinstance(_cached, str):
            try:
                import json as _json_mod
                _cached = _json_mod.loads(_cached)
                _log.info(f"[GLOBAL-KINASE] Deserialized string kinase_analysis_data for order {order_id}")
            except Exception:
                _log.warning(f"[GLOBAL-KINASE] Failed to parse string kinase_analysis_data for order {order_id}")
                _cached = {}
        if not isinstance(_cached, dict):
            _cached = {}
        _cached_hash = _cached.get("_cache_hash", "")
        if _cache_probe or _cached_hash == _cache_hash:
            _log.info(f"[GLOBAL-KINASE] Cache HIT for order {order_id} (probe={_cache_probe}, hash={_cache_hash})")
            return {
                "order_id": order_id,
                "kinase_modules": _cached.get("kinase_modules", []),
                "unassigned_ptms": _cached.get("unassigned_ptms", []),
                "annotation_details": _cached.get("annotation_details", []),
                "summary": _cached.get("summary", {}),
                "cowave_cross_analysis": _cached.get("cowave_cross_analysis", {}),
                "temporal_cascade": _cached.get("temporal_cascade", {}),
                "effector_proteins": _cached.get("effector_proteins", []),
                "wave_kinase_profile": _cached.get("wave_kinase_profile", []),
                "_cached": True,
                "_cache_hash": _cached_hash or _cache_hash,
            }
        else:
            _log.info(f"[GLOBAL-KINASE] Cache MISS for order {order_id} (stored={_cached_hash}, current={_cache_hash})")
    else:
        _log.info(f"[GLOBAL-KINASE] No cache or force_refresh for order {order_id}")

    # If this is just a cache probe and no cache was found, return empty (don't compute)
    if _cache_probe:
        _log.info(f"[GLOBAL-KINASE] Cache probe with no cache found for order {order_id}, returning empty")
        return {
            "order_id": order_id,
            "kinase_modules": [],
            "unassigned_ptms": [],
            "annotation_details": [],
            "summary": {},
            "cowave_cross_analysis": {},
            "temporal_cascade": {},
            "effector_proteins": [],
            "wave_kinase_profile": [],
            "_cached": False,
        }

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
            # Filter out invalid kinase names (stop words, too short, generic terms)
            _KINASE_STOP_WORDS = {
                "OF", "THE", "AND", "FOR", "WITH", "THIS", "THAT", "FROM",
                "BY", "TO", "IN", "ON", "AT", "IS", "IT", "AS", "OR", "AN",
                "BE", "IF", "NO", "NOT", "BUT", "ALL", "CAN", "HAD", "HAS",
                "HER", "HIS", "HOW", "ITS", "MAY", "NEW", "NOW", "OLD", "OUR",
                "OUT", "OWN", "SAY", "SHE", "TOO", "USE", "WAY", "WHO", "BOY",
                "DID", "GET", "HIM", "LET", "PUT", "RUN", "SET", "TOP", "WHY",
                "CELL", "GENE", "PROTEIN", "DOMAIN", "SITE", "TYPE", "ROLE",
                "ACTIVITY", "FUNCTION", "PATHWAY", "SIGNAL", "TARGET", "EFFECT",
                "RESULT", "LEVEL", "FACTOR", "COMPLEX", "FAMILY", "GROUP",
                "REGION", "SEQUENCE", "RESIDUE", "MOTIF", "SUBSTRATE",
            }
            if not canon or len(canon) < 3 or canon in _KINASE_STOP_WORDS:
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
    is_ubi_global = order.ptm_type == "ubiquitylation"
    for ann in annotations:
        if ann.get("known_kinases"):
            continue  # Already assigned as confirmed

        gene = ann.get("gene", "")
        position = ann.get("position", "")
        ptm_key = f"{gene}_{position}"  # Use gene_position format to match frontend chart keys

        motif_families = set()
        motif_display_names = {}  # canonical → display name
        for mp in ann.get("motif_predicted_kinases", []):
            cf = mp.get("canonical_family", mp.get("kinase_family", ""))
            display = mp.get("kinase_family", cf)
            for part in cf.split("/"):
                if part and len(part) >= 2:
                    motif_families.add(part)
                    motif_display_names[part] = display

        # Try to match with existing kinase modules
        matched_kinases = []
        for canon, info in kinase_members.items():
            for mf in motif_families:
                if are_kinases_same_family(canon, mf):
                    matched_kinases.append(canon)
                    break

        if matched_kinases:
            # ── Temporal-aware best kinase selection ──
            # Instead of just picking the kinase with most confirmed members,
            # use temporal context to pick the best-fitting kinase for this PTM
            ptm_peak_min = None
            ptm_wave_info = {}
            if cowave_modules_input:
                for cw in cowave_modules_input:
                    cw_ptm_set = set(cw.get("ptm_keys", []) or cw.get("ptms", []))
                    if ptm_key in cw_ptm_set:
                        cw_label = cw.get("label", "")
                        peak_match = re.search(r'peak:\s*([\w.]+)', cw_label)
                        if peak_match:
                            _pk_str = peak_match.group(1)
                            _pk_m = re.match(r'([\d.]+)\s*(h|hr|hour|min|m)?', _pk_str, re.IGNORECASE)
                            if _pk_m:
                                _pk_val = float(_pk_m.group(1))
                                _pk_unit = (_pk_m.group(2) or 'h').lower()
                                ptm_peak_min = _pk_val if _pk_unit.startswith('m') else _pk_val * 60
                            else:
                                ptm_peak_min = None
                        break

            if ptm_peak_min is not None and len(matched_kinases) > 1:
                # Score each candidate kinase by temporal fit
                try:
                    from app.services.temporal_kinase_scoring import compute_temporal_fit_score
                    scored_candidates = []
                    for c in matched_kinases:
                        t_score = compute_temporal_fit_score(ptm_peak_min, c)
                        # Combine temporal score with confirmed count (weighted)
                        conf_count = len(kinase_members[c]["confirmed"])
                        combined = t_score * 0.6 + min(1.0, conf_count / 20.0) * 0.4
                        scored_candidates.append((c, combined))
                    scored_candidates.sort(key=lambda x: x[1], reverse=True)
                    best_canon = scored_candidates[0][0]
                except Exception:
                    best_canon = max(matched_kinases, key=lambda c: len(kinase_members[c]["confirmed"]))
            else:
                best_canon = max(matched_kinases, key=lambda c: len(kinase_members[c]["confirmed"]))

            if ptm_key not in [m["key"] for m in kinase_members[best_canon]["inferred"]]:
                kinase_members[best_canon]["inferred"].append({
                    "key": ptm_key,
                    "gene": gene,
                    "position": position,
                    "membership": "inferred",
                    "evidence": f"motif match ({', '.join(motif_families)})",
                })
        elif motif_families and is_ubi_global:
            # Ubiquitylation: if motif prediction exists but no anchor module yet,
            # create a new E3 module from the motif prediction itself
            # (phosphorylation requires anchor kinase from literature; ubi relies more on motif/degron)
            for mf in sorted(motif_families):
                display = motif_display_names.get(mf, mf)
                if mf not in kinase_members:
                    kinase_members[mf] = {
                        "kinase": display,
                        "canonical": mf,
                        "sources": set(),
                        "confirmed": [],
                        "inferred": [],
                    }
                kinase_members[mf]["sources"].add("motif_prediction")
                if ptm_key not in [m["key"] for m in kinase_members[mf]["inferred"]]:
                    kinase_members[mf]["inferred"].append({
                        "key": ptm_key,
                        "gene": gene,
                        "position": position,
                        "membership": "inferred",
                        "evidence": f"degron/motif prediction ({display})",
                    })
                break  # Assign to the first (best) motif prediction only

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

    # ── 5a. v9.44: Co-wave Confidence Boost for Kinase Modules ─────────────
    # A kinase module is more confident when its substrates co-move temporally.
    # confidence_score = base_score + cowave_boost
    #   base_score: confirmed_ratio * source_diversity
    #   cowave_boost: proportion of members in co-wave groups * group_coherence
    for km in kinase_module_list:
        total = km["total_count"]
        if total == 0:
            km["confidence_score"] = 0.0
            km["cowave_boost"] = 0.0
            continue

        # Base confidence: confirmed ratio + source diversity
        confirmed_ratio = km["confirmed_count"] / total
        source_diversity = min(1.0, km["source_count"] / 3.0)  # max 3 sources = 1.0
        base_score = confirmed_ratio * 0.6 + source_diversity * 0.4

        # Co-wave boost: how many members are in co-wave groups?
        cowave_member_count = 0
        max_shared_ratio = 0.0
        for cw_ov in km.get("cowave_overlap", []):
            shared_count = len(cw_ov.get("shared_ptms", []))
            cowave_member_count += shared_count
            # Find the co-wave group that has the highest overlap with this kinase
            if shared_count > 0:
                ratio = shared_count / total
                if ratio > max_shared_ratio:
                    max_shared_ratio = ratio

        # cowave_boost: [0, 1] — higher when more substrates are in same co-wave
        # Dedup: a PTM can be in multiple co-waves, cap at total
        cowave_coverage = min(1.0, cowave_member_count / total)
        # Coherence bonus: if a single co-wave contains most of this kinase's substrates
        coherence_bonus = max_shared_ratio ** 0.5  # sqrt to soften
        cowave_boost = cowave_coverage * 0.5 + coherence_bonus * 0.5

        # Final confidence: base + boost (capped at 1.0)
        km["confidence_score"] = round(min(1.0, base_score * 0.6 + cowave_boost * 0.4 + base_score * cowave_boost * 0.3), 3)
        km["cowave_boost"] = round(cowave_boost, 3)

    # Sort by confidence_score descending (replaces simple total_count sort)
    kinase_module_list.sort(key=lambda x: (x.get("confidence_score", 0), x["total_count"]), reverse=True)

    # ── 5b. Smart Signal Decomposition: Temporal Kinase Redistribution ─────
    # Disambiguate over-concentrated kinase modules using temporal context
    try:
        from app.services.temporal_kinase_scoring import (
            redistribute_kinase_assignments,
            build_wave_kinase_profile,
        )
        treatment_ctx = order.treatment or ""
        kinase_module_list = redistribute_kinase_assignments(
            kinase_module_list,
            cowave_modules_input or [],
            treatment_context=treatment_ctx,
        )
        # Build wave-kinase profile for enhanced receptor inference
        wave_kinase_profile = build_wave_kinase_profile(
            kinase_module_list,
            cowave_modules_input or [],
        )
    except Exception as e:
        import traceback
        _log.warning(f"[TEMPORAL-SCORING] Redistribution failed: {e}\n{traceback.format_exc()}")
        wave_kinase_profile = []

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

    # ── 9. Non-PTM Effector Proteins (4th layer for Signal Flow) ─────────
    # Extract Non-PTM proteins connected to PTM substrates via STRING/BioGRID
    # with significant abundance changes across timepoints
    effector_proteins = []
    try:
        import csv as _csv
        output_dir = Path(settings.OUTPUT_DIR) / order.order_code

        # 9a. Load unified TSV for ALL protein temporal profiles
        _protein_temporal: dict = {}  # gene_upper -> {condition -> protein_log2fc}
        _ptm_temporal: dict = {}      # "GENE_SITE" -> {condition -> ptm_log2fc}  (for substrate PTM peaks)
        _protein_data_type: dict = {}  # gene_upper -> Data_Type
        if output_dir.exists():
            tsv_candidates = (
                list(output_dir.glob("unified_protein_data_enriched_bio_enriched*.tsv"))
                + list(output_dir.glob("unified_protein_data_enriched*.tsv"))
            )
            if tsv_candidates:
                tsv_path = tsv_candidates[0]
                _log.info(f"[GLOBAL-KINASE] Loading Non-PTM temporal profiles from {tsv_path.name}")
                with open(tsv_path, "r", encoding="utf-8") as _f:
                    reader = _csv.DictReader(_f, delimiter="\t")
                    for row in reader:
                        gene = (row.get("Gene.Name") or row.get("Gene_Name") or "").strip()
                        gene_upper = gene.upper()
                        if not gene_upper:
                            continue
                        dt = row.get("Data_Type", "")
                        cond = (row.get("Condition") or "").strip()
                        pfc_raw = row.get("Protein_Log2FC") or row.get("Log2FC") or "0"
                        try:
                            pfc = float(pfc_raw) if pfc_raw and pfc_raw.lower() not in ("na", "nan", "") else 0.0
                        except (TypeError, ValueError):
                            pfc = 0.0
                        if gene_upper not in _protein_temporal:
                            _protein_temporal[gene_upper] = {}
                        if cond:
                            _protein_temporal[gene_upper][cond] = pfc
                        _protein_data_type[gene_upper] = dt
                        # Also load PTM_Relative_Log2FC for substrate PTM peak calculation
                        ptm_fc_raw = row.get("PTM_Relative_Log2FC") or row.get("PTM_Log2FC") or row.get("ptm_log2fc") or ""
                        ptm_pos = (row.get("PTM_Position") or row.get("Position") or "").strip()
                        if ptm_fc_raw and ptm_fc_raw.lower() not in ("na", "nan", "") and ptm_pos and cond:
                            try:
                                ptm_fc = float(ptm_fc_raw)
                                ptm_key = f"{gene_upper}_{ptm_pos.upper()}"
                                if ptm_key not in _ptm_temporal:
                                    _ptm_temporal[ptm_key] = {}
                                _ptm_temporal[ptm_key][cond] = ptm_fc
                            except (TypeError, ValueError):
                                pass
                _log.info(f"[GLOBAL-KINASE] Loaded temporal profiles for {len(_protein_temporal)} genes")

        # 9b. Identify PTM substrate genes (from kinase modules)
        _substrate_genes: set = set()
        _substrate_kinase_map: dict = {}  # gene_upper -> set of kinase names
        _substrate_ptm_sites: dict = {}   # gene_upper -> list of "GENE_SITE" keys
        for km in kinase_module_list:
            for m in km["members"]:
                g_upper = m["gene"].upper()
                _substrate_genes.add(g_upper)
                if g_upper not in _substrate_kinase_map:
                    _substrate_kinase_map[g_upper] = set()
                _substrate_kinase_map[g_upper].add(km["kinase"])
                # Track PTM sites for temporal concordance
                pos = (m.get("position") or "").strip().upper()
                if pos:
                    ptm_key = f"{g_upper}_{pos}"
                    if g_upper not in _substrate_ptm_sites:
                        _substrate_ptm_sites[g_upper] = []
                    if ptm_key not in _substrate_ptm_sites[g_upper]:
                        _substrate_ptm_sites[g_upper].append(ptm_key)
        # Also include unassigned PTM genes as substrates
        for ua in unassigned:
            g_upper = ua["gene"].upper()
            _substrate_genes.add(g_upper)
            pos = (ua.get("position") or "").strip().upper()
            if pos:
                ptm_key = f"{g_upper}_{pos}"
                if g_upper not in _substrate_ptm_sites:
                    _substrate_ptm_sites[g_upper] = []
                if ptm_key not in _substrate_ptm_sites[g_upper]:
                    _substrate_ptm_sites[g_upper].append(ptm_key)

        # 9c. Load enriched_ptm_data JSON for STRING/BioGRID interactions
        file_suffix = "_phospho" if order.ptm_type == "phosphorylation" else "_ubi"
        enriched_path = output_dir / f"enriched_ptm_data{file_suffix}.json"
        _substrate_to_partners: dict = {}  # substrate_gene_upper -> [{partner, source, score}]
        if enriched_path.exists():
            import json as _json2
            with open(enriched_path, "r", encoding="utf-8") as _ef:
                enriched_list = _json2.load(_ef)
            for ptm_item in enriched_list:
                gene = (ptm_item.get("gene") or ptm_item.get("Gene.Name", "")).strip()
                gene_upper = gene.upper()
                if gene_upper not in _substrate_genes:
                    continue
                rag = ptm_item.get("rag_enrichment", {})
                if not isinstance(rag, dict):
                    continue
                # STRING interactions
                # Prefer string_db.interactions (dict list) over string_interactions (str list)
                _sdb_ints = rag.get("string_db", {}).get("interactions", []) if isinstance(rag.get("string_db"), dict) else []
                if _sdb_ints:
                    string_ints = _sdb_ints
                else:
                    # Fallback: parse 'GENE(score)' string format from string_interactions
                    _raw = rag.get("string_interactions", []) or []
                    string_ints = []
                    import re as _re
                    for _s in _raw:
                        if isinstance(_s, dict):
                            string_ints.append(_s)
                        elif isinstance(_s, str):
                            _m = _re.match(r"^(.+)\(([0-9.]+)\)$", _s.strip())
                            if _m:
                                string_ints.append({"partner": _m.group(1), "score": float(_m.group(2))})
                for si in (string_ints or []):
                    partner = (si.get("partner") or "").strip()
                    partner_upper = partner.upper()
                    if not partner or partner_upper in _substrate_genes:
                        continue  # Skip PTM substrates (only want Non-PTM partners)
                    score = si.get("score", 0)
                    # string_db scores are 0-1 float; normalize to 0-1000 scale if needed
                    if isinstance(score, float) and score <= 1.0:
                        score = score * 1000
                    if score < 400:  # STRING confidence threshold
                        continue
                    if gene_upper not in _substrate_to_partners:
                        _substrate_to_partners[gene_upper] = []
                    _substrate_to_partners[gene_upper].append({
                        "partner": partner,
                        "partner_upper": partner_upper,
                        "source": "STRING",
                        "score": score,
                    })
                # BioGRID interactions
                biogrid = rag.get("biogrid", {})
                biogrid_ints = biogrid.get("interactions", []) if isinstance(biogrid, dict) else []
                for bi in biogrid_ints:
                    int_a = (bi.get("interactor_a", "") or "").strip().upper()
                    int_b = (bi.get("interactor_b", "") or "").strip().upper()
                    partner_upper = int_b if int_a == gene_upper else int_a if int_b == gene_upper else ""
                    if not partner_upper or partner_upper in _substrate_genes:
                        continue
                    partner_name = int_b if int_a == gene_upper else int_a
                    if gene_upper not in _substrate_to_partners:
                        _substrate_to_partners[gene_upper] = []
                    _substrate_to_partners[gene_upper].append({
                        "partner": partner_name,
                        "partner_upper": partner_upper,
                        "source": "BioGRID",
                        "score": 0,
                    })

        # 9d. Build effector protein list with evidence scoring
        _effector_fc_threshold = 0.3  # |log2FC| threshold for significance
        _seen_effectors: dict = {}  # partner_upper -> effector dict

        # Helper: get substrate PTM peak condition and direction
        def _get_substrate_ptm_peak(sub_gene_upper: str):
            """Return (peak_condition, peak_fc, peak_minutes) for a substrate's PTM."""
            sites = _substrate_ptm_sites.get(sub_gene_upper, [])
            best_peak = None
            for site_key in sites:
                site_temporal = _ptm_temporal.get(site_key, {})
                if not site_temporal:
                    continue
                pk = max(site_temporal.items(), key=lambda x: abs(x[1]))
                if best_peak is None or abs(pk[1]) > abs(best_peak[1]):
                    best_peak = pk
            if best_peak is None:
                # Fallback: use protein-level temporal for this substrate
                prot_temporal = _protein_temporal.get(sub_gene_upper, {})
                if prot_temporal:
                    best_peak = max(prot_temporal.items(), key=lambda x: abs(x[1]))
            if best_peak:
                return best_peak[0], best_peak[1], _parse_time_minutes(best_peak[0])
            return None, 0.0, 0.0

        for sub_gene, partners in _substrate_to_partners.items():
            for p in partners:
                pu = p["partner_upper"]
                temporal = _protein_temporal.get(pu, {})
                if not temporal:
                    continue
                max_abs_fc = max((abs(v) for v in temporal.values()), default=0)
                if max_abs_fc < _effector_fc_threshold:
                    continue
                if pu not in _seen_effectors:
                    peak_cond = max(temporal.items(), key=lambda x: abs(x[1]))
                    tp_list = [
                        {"condition": c, "protein_log2fc": round(v, 4)}
                        for c, v in sorted(temporal.items(), key=lambda x: _parse_time_minutes(x[0]))
                    ]
                    data_type = _protein_data_type.get(pu, "")
                    _seen_effectors[pu] = {
                        "gene": p["partner"],
                        "data_type": data_type,
                        "connected_substrates": [],
                        "temporal_profile": tp_list,
                        "max_abs_fc": round(max_abs_fc, 4),
                        "peak_condition": peak_cond[0],
                        "peak_fc": round(peak_cond[1], 4),
                        "peak_minutes": _parse_time_minutes(peak_cond[0]),
                        "sources": set(),
                        # Evidence scoring fields (computed in 9e)
                        "concordant_count": 0,
                        "discordant_count": 0,
                        "directionality": "unknown",
                        "time_lag_minutes": None,
                        "evidence_strength": "weak",
                    }
                _seen_effectors[pu]["sources"].add(p["source"])
                # Compute per-substrate concordance
                sub_peak_cond, sub_peak_fc, sub_peak_min = _get_substrate_ptm_peak(sub_gene)
                eff_peak_fc = _seen_effectors[pu]["peak_fc"]
                # Directionality: same sign = concordant
                is_concordant = (sub_peak_fc > 0 and eff_peak_fc > 0) or (sub_peak_fc < 0 and eff_peak_fc < 0)
                kinases_for_sub = list(_substrate_kinase_map.get(sub_gene, set()))
                _seen_effectors[pu]["connected_substrates"].append({
                    "gene": sub_gene,
                    "kinases": kinases_for_sub[:3],
                    "source": p["source"],
                    "substrate_peak_fc": round(sub_peak_fc, 4) if sub_peak_fc else 0,
                    "substrate_peak_cond": sub_peak_cond or "",
                    "concordant": is_concordant,
                })

        # 9d-2. Add ALL non-PTM proteins from TSV (Data_Type == "Protein_Only")
        #       that have significant expression changes, regardless of PPI relationship
        _non_ptm_added = 0
        for _gene_up, _dt in _protein_data_type.items():
            if _dt != "Protein_Only":
                continue
            if _gene_up in _substrate_genes:
                continue  # Skip PTM substrates
            if _gene_up in _seen_effectors:
                continue  # Already added via PPI
            _temporal = _protein_temporal.get(_gene_up, {})
            if not _temporal:
                continue
            _max_fc = max((abs(v) for v in _temporal.values()), default=0)
            if _max_fc < _effector_fc_threshold:
                continue
            _pk = max(_temporal.items(), key=lambda x: abs(x[1]))
            _tp = [
                {"condition": c, "protein_log2fc": round(v, 4)}
                for c, v in sorted(_temporal.items(), key=lambda x: _parse_time_minutes(x[0]))
            ]
            _seen_effectors[_gene_up] = {
                "gene": _gene_up,
                "data_type": _dt,
                "connected_substrates": [],
                "temporal_profile": _tp,
                "max_abs_fc": round(_max_fc, 4),
                "peak_condition": _pk[0],
                "peak_fc": round(_pk[1], 4),
                "peak_minutes": _parse_time_minutes(_pk[0]),
                "sources": [],
                "concordant_count": 0,
                "discordant_count": 0,
                "directionality": "expression_only",
                "time_lag_minutes": None,
                "evidence_strength": "expression_only",
            }
            _non_ptm_added += 1
        _log.info(
            f"[GLOBAL-KINASE] Added {_non_ptm_added} additional non-PTM proteins "
            f"from TSV (Data_Type=Protein_Only, |log2FC| > {_effector_fc_threshold})"
        )

        # 9e. Deduplicate, compute evidence scoring, and convert sets
        for pu, eff in _seen_effectors.items():
            eff["sources"] = sorted(eff["sources"])
            # Deduplicate connected_substrates
            seen_subs = set()
            unique_subs = []
            for s in eff["connected_substrates"]:
                if s["gene"] not in seen_subs:
                    seen_subs.add(s["gene"])
                    unique_subs.append(s)
            eff["connected_substrates"] = unique_subs

            # Concordance scoring
            concordant = sum(1 for s in unique_subs if s.get("concordant"))
            discordant = len(unique_subs) - concordant
            eff["concordant_count"] = concordant
            eff["discordant_count"] = discordant
            total_subs = len(unique_subs)
            if total_subs == 0:
                eff["directionality"] = "unknown"
            elif concordant == total_subs:
                eff["directionality"] = "concordant"
            elif discordant == total_subs:
                eff["directionality"] = "discordant"
            else:
                eff["directionality"] = "mixed"

            # Time-lag: average (effector peak - substrate peak) across connected substrates
            eff_peak_min = eff.get("peak_minutes", 0)
            lag_values = []
            for s in unique_subs:
                sub_cond = s.get("substrate_peak_cond", "")
                if sub_cond:
                    sub_min = _parse_time_minutes(sub_cond)
                    lag_values.append(eff_peak_min - sub_min)
            if lag_values:
                avg_lag = sum(lag_values) / len(lag_values)
                eff["time_lag_minutes"] = round(avg_lag, 1)
            else:
                eff["time_lag_minutes"] = None

            # Evidence strength scoring
            score = 0
            # Multi-substrate support: more substrates = stronger
            if total_subs >= 3:
                score += 3
            elif total_subs >= 2:
                score += 2
            else:
                score += 1
            # Concordance bonus
            if eff["directionality"] == "concordant":
                score += 2
            elif eff["directionality"] == "mixed" and concordant > discordant:
                score += 1
            # Temporal lag bonus: effector peaks AFTER substrate (lag > 0) = causal direction
            if eff["time_lag_minutes"] is not None and eff["time_lag_minutes"] > 0:
                score += 2
            # Fold-change magnitude bonus
            if eff["max_abs_fc"] >= 1.0:
                score += 1
            # Multiple PPI sources bonus
            if len(eff["sources"]) >= 2:
                score += 1

            if score >= 6:
                eff["evidence_strength"] = "strong"
            elif score >= 4:
                eff["evidence_strength"] = "moderate"
            else:
                eff["evidence_strength"] = "weak"
            eff["evidence_score"] = score

        # Sort by evidence_score descending, then max_abs_fc descending
        effector_proteins = sorted(
            _seen_effectors.values(),
            key=lambda x: (x.get("evidence_score", 0), x["max_abs_fc"]),
            reverse=True,
        )
        _log.info(
            f"[GLOBAL-KINASE] Non-PTM effectors: {len(effector_proteins)} proteins "
            f"(from {len(_substrate_to_partners)} substrate-partner connections, "
            f"threshold |log2FC| > {_effector_fc_threshold})"
        )
    except Exception as _eff_err:
        _log.warning(f"[GLOBAL-KINASE] Non-PTM effector extraction failed: {_eff_err}", exc_info=True)
        effector_proteins = []

    _log.info(
        f"[GLOBAL-KINASE] Complete: {len(kinase_module_list)} kinase modules, "
        f"{summary['total_confirmed']} confirmed, {summary['total_inferred']} inferred, "
        f"{len(unassigned)} unassigned, "
        f"{len(temporal_cascade.get('timepoints', []))} cascade timepoints, "
        f"{len(effector_proteins)} Non-PTM effectors"
    )

    # ── Persist kinase analysis data to DB for use in report generation ──
    try:
        from datetime import datetime as _dt
        result_obj = await db.execute(select(Order).where(Order.id == order_id))
        order_obj = result_obj.scalar_one_or_none()
        if order_obj:
            # v9.48.1: Strip annotation_details (large) from DB cache to avoid MySQL packet limits.
            # annotation_details can be re-derived from enriched JSON if needed.
            # Also strip temporal_profile from effector_proteins to reduce size.
            _effectors_slim = [
                {k: v for k, v in eff.items() if k != "temporal_profile"}
                for eff in (effector_proteins or [])[:200]
            ]
            order_obj.kinase_analysis_data = {
                "kinase_modules": kinase_module_list,
                "temporal_cascade": temporal_cascade,
                "cowave_cross_analysis": cowave_cross,
                "summary": summary,
                "effector_proteins": _effectors_slim,
                "wave_kinase_profile": wave_kinase_profile,
                "unassigned_ptms": unassigned,
                "saved_at": _dt.utcnow().isoformat(),
                "_cache_hash": _cache_hash,
            }
            await db.commit()
            _log.info(f"[GLOBAL-KINASE] Saved kinase_analysis_data to order {order_id} DB (slim, no annotation_details)")
    except Exception as _e:
        import traceback as _tb
        _log.warning(f"[GLOBAL-KINASE] Failed to save kinase_analysis_data to DB: {_e}\n{_tb.format_exc()}")

    return {
        "order_id": order_id,
        "kinase_modules": kinase_module_list,
        "unassigned_ptms": unassigned,
        "annotation_details": annotations,
        "summary": summary,
        "cowave_cross_analysis": cowave_cross,
        "temporal_cascade": temporal_cascade,
        "effector_proteins": effector_proteins,
        "wave_kinase_profile": wave_kinase_profile,
        "_cache_hash": _cache_hash,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Save merged kinase analysis data (for batched Global Annotate)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{order_id}/save-kinase-analysis-data")
async def save_kinase_analysis_data(
    order_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Save merged kinase analysis data to DB.

    When Global Annotate runs in batched mode (to avoid 524 timeout),
    the frontend merges results from multiple batch calls and then
    saves the final merged result via this endpoint.

    This ensures kinase_analysis_data in the DB reflects the COMPLETE
    analysis across all PTMs, not just the last batch.

    Request body: same structure as GlobalKinaseModuleResponse
    """
    import logging
    from datetime import datetime as _dt

    _log = logging.getLogger("save_kinase_analysis")

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    await _require_write_access(order, user, db)

    kinase_modules = body.get("kinase_modules", [])
    temporal_cascade = body.get("temporal_cascade", {})
    cowave_cross_analysis = body.get("cowave_cross_analysis", {})
    summary = body.get("summary", {})
    effector_proteins = body.get("effector_proteins", [])
    wave_kinase_profile = body.get("wave_kinase_profile", [])
    # Preserve _cache_hash from body (set by global-kinase-modules endpoint)
    _cache_hash = body.get("_cache_hash", "")
    order.kinase_analysis_data = {
        "kinase_modules": kinase_modules,
        "temporal_cascade": temporal_cascade,
        "cowave_cross_analysis": cowave_cross_analysis,
        "summary": summary,
        "effector_proteins": effector_proteins,
        "wave_kinase_profile": wave_kinase_profile,
        "saved_at": _dt.utcnow().isoformat(),
        "source": "batched_merge",
        "_cache_hash": _cache_hash,
    }
    await db.commit()

    _log.info(
        f"[SAVE-KINASE] Saved merged kinase_analysis_data to order {order_id}: "
        f"{len(kinase_modules)} modules, {len(effector_proteins)} effectors"
    )

    return {"status": "ok", "order_id": order_id, "modules_saved": len(kinase_modules)}


# ─────────────────────────────────────────────────────────────────────────────
# v9.44: Kinase Activity Temporal Heatmap (compute + cache)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{order_id}/kinase-activity-heatmap")
async def kinase_activity_heatmap(
    order_id: int,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Compute Kinase Activity Temporal Scores for heatmap/line chart.

    v11.3: Stratified Clustering + Winsorized Mean scoring.
    - Substrates grouped by magnitude tier (Strong >5.0, Moderate 2-5, Weak <=2.0)
    - Within each tier: K-Means with Absolute Correlation (1-|r|) distance
    - Dominant cluster selected by: coherence × √size × |peak_score| × tier_bonus
    - Per-condition score = Winsorized Mean (5th/95th percentile)
    - Legacy up_sums/down_sums retained for backward compatibility
    - Substrates classified as exclusive (mapped to 1 kinase) or shared (2+ kinases)

    Request body:
      - kinase_modules: [{kinase, ptms: [{gene, position}], confidence_score}]
      - force_refresh: bool (default false)

    Response:
      - kinase_scores: [{kinase, scores, substrate_count, confidence, peak_condition, peak_score,
                         cluster_details, coact_counts, exclusive_sums, shared_sums, ...}]
      - conditions: [str]  (ordered)
      - _cached: bool
    """
    import hashlib
    from datetime import datetime as _dt

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    await _check_order_access_async(order, user, db)

    kinase_modules = body.get("kinase_modules", [])
    force_refresh = body.get("force_refresh", False)

    # Cache key
    km_keys = sorted([m.get("kinase", "") for m in kinase_modules])
    hash_input = f"{order_id}|{len(kinase_modules)}|{'|'.join(km_keys[:30])}"
    cache_hash = hashlib.md5(hash_input.encode()).hexdigest()[:12]

    # Check cache — v11.3 Pure Renderer pattern:
    # Priority 1: If pipeline already computed & stored results (same hash), serve directly.
    # Priority 2: If force_refresh, recompute from scratch.
    if not force_refresh and order.kinase_activity_heatmap:
        cached = order.kinase_activity_heatmap
        if cached.get("_cache_hash") == cache_hash:
            return {**cached, "_cached": True}
        # Even if hash differs (kinase modules changed), still serve stale cache
        # with a flag so frontend knows it's outdated but usable.
        # Only recompute below if force_refresh or no cache at all.
        if not force_refresh:
            return {**cached, "_cached": True, "_stale": True}

    # Load vector data (time-series)
    from app.config import get_settings
    settings = get_settings()
    output_dir = Path(settings.OUTPUT_DIR) / order.order_code
    file_suffix = "_phospho" if order.ptm_type == "phosphorylation" else "_ubi"

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
                    q_val_raw = row.get("q_value", "")
                    try:
                        rel_fc = float(rel_fc) if rel_fc else 0.0
                    except ValueError:
                        rel_fc = 0.0
                    try:
                        q_val = float(q_val_raw) if q_val_raw and q_val_raw.strip().lower() not in ("", "nan") else None
                    except (ValueError, TypeError):
                        q_val = None
                    vector_data.append({
                        "gene": gene, "position": str(pos),
                        "condition": cond, "log2fc": rel_fc, "q_value": q_val,
                    })
            break

    if not vector_data:
        raise HTTPException(status_code=400, detail="No vector data found. Run preprocessing first.")

    # Build PTM key → condition → log2fc map
    ptm_timeseries: dict[str, dict[str, float]] = {}
    ptm_qvalues: dict[str, dict[str, float | None]] = {}
    all_conditions: set[str] = set()
    for row in vector_data:
        key = f"{row['gene'].upper()}_{row['position'].upper()}"
        cond = row["condition"]
        all_conditions.add(cond)
        if key not in ptm_timeseries:
            ptm_timeseries[key] = {}
            ptm_qvalues[key] = {}
        # Cap extreme Log2FC values (pseudocount artifacts)
        _raw_fc_raw = row["log2fc"]
        try:
            _raw_fc = float(_raw_fc_raw) if _raw_fc_raw is not None else 0.0
        except (ValueError, TypeError):
            _raw_fc = 0.0
        # v11.2: Store raw Log2FC (no cap). Winsorization applied per-kinase during scoring.
        ptm_timeseries[key][cond] = _raw_fc
        ptm_qvalues[key][cond] = row["q_value"]

    # Sort conditions (try numeric extraction for time-series)
    import re
    def _cond_sort_key(c: str):
        nums = re.findall(r"[\d.]+", c)
        return float(nums[0]) if nums else c
    conditions_sorted = sorted(all_conditions, key=_cond_sort_key)

    # ── Build PTM → kinase reverse map (for exclusive/shared classification) ──
    ptm_to_kinases: dict[str, list[str]] = {}  # ptm_key -> [kinase_names]
    for km in kinase_modules:
        kn = km.get("kinase", "")
        for ptm in km.get("ptms", []):
            pk = f"{ptm.get('gene', '').upper()}_{str(ptm.get('position', '')).upper()}"
            ptm_to_kinases.setdefault(pk, []).append(kn)

    # ── Co-activation Sum Scoring ──
    # Threshold: include substrate if q < 0.05 OR |Log2FC| >= 0.3
    FC_THRESHOLD = 0.3
    Q_THRESHOLD = 0.05

    # Signal tier thresholds
    DE_NOVO_THRESHOLD = 2.0   # |FC| >= 2.0
    REGULATED_THRESHOLD = 0.58  # 0.58 <= |FC| < 2.0
    # minor: 0.3 <= |FC| < 0.58

    def _classify_tier(fc_abs: float) -> str:
        if fc_abs >= DE_NOVO_THRESHOLD:
            return "de_novo"
        elif fc_abs >= REGULATED_THRESHOLD:
            return "regulated"
        else:
            return "minor"

    import numpy as np
    n_conditions = len(conditions_sorted)

    # ── v11.0: Pure-numpy K-Means for substrate temporal clustering ──
    MIN_SUBSTRATES_FOR_CLUSTERING = 10

    def _numpy_kmeans(data: np.ndarray, k: int, n_init: int = 10,
                      max_iter: int = 300, seed: int = 42) -> np.ndarray:
        """K-Means clustering using only numpy. Returns label array."""
        rng = np.random.RandomState(seed)
        n_samples, n_features = data.shape
        best_labels = np.zeros(n_samples, dtype=int)
        best_inertia = np.inf
        for _ in range(n_init):
            centers = np.empty((k, n_features), dtype=data.dtype)
            idx = rng.randint(0, n_samples)
            centers[0] = data[idx]
            for c_idx in range(1, k):
                dists = np.min(
                    np.sum((data[:, None, :] - centers[None, :c_idx, :]) ** 2, axis=2),
                    axis=1,
                )
                probs = dists / max(dists.sum(), 1e-12)
                idx = rng.choice(n_samples, p=probs)
                centers[c_idx] = data[idx]
            labels = np.zeros(n_samples, dtype=int)
            for _it in range(max_iter):
                dists = np.sum(
                    (data[:, None, :] - centers[None, :, :]) ** 2, axis=2
                )
                new_labels = np.argmin(dists, axis=1)
                if np.array_equal(new_labels, labels) and _it > 0:
                    break
                labels = new_labels
                for ci in range(k):
                    mask = labels == ci
                    if mask.any():
                        centers[ci] = data[mask].mean(axis=0)
            inertia = sum(
                np.sum((data[labels == ci] - centers[ci]) ** 2)
                for ci in range(k)
            )
            if inertia < best_inertia:
                best_inertia = inertia
                best_labels = labels.copy()
        return best_labels

    def _compute_coherence_for_keys(ptm_keys_list):
        """Compute mean pairwise |Pearson r| for a list of PTM keys.
        v11.3: Uses absolute correlation to correctly handle anti-correlated
        substrates within the same regulatory module."""
        vectors = []
        for pk in ptm_keys_list:
            ts = ptm_timeseries.get(pk, {})
            if ts:
                row = [ts.get(c, 0.0) for c in conditions_sorted]
                if any(v != 0 for v in row):
                    vectors.append(row)
        if len(vectors) < 2:
            return 0.0
        try:
            arr = np.array(vectors)
            corr_matrix = np.corrcoef(arr)
            n = corr_matrix.shape[0]
            upper = [abs(corr_matrix[i][j]) for i in range(n) for j in range(i + 1, n)
                     if not np.isnan(corr_matrix[i][j])]
            return round(float(np.mean(upper)), 3) if upper else 0.0
        except Exception:
            return 0.0

    # ── Winsorized Mean constants (v11.2+) ──
    WINSORIZE_LOWER = 5   # percentile
    WINSORIZE_UPPER = 95  # percentile

    # v11.3: Magnitude tier thresholds for Stratified Clustering
    TIER1_THRESHOLD = 5.0   # De novo / Strong: max |Log2FC| > 5.0
    TIER2_THRESHOLD = 2.0   # Regulated / Moderate: 2.0 < max |Log2FC| <= 5.0
    # Tier 3: max |Log2FC| <= 2.0 (Minor / Weak)

    def _assign_tier_api(fc_vector):
        """Assign magnitude tier based on max absolute Log2FC."""
        max_abs = max(abs(v) for v in fc_vector) if fc_vector else 0
        if max_abs > TIER1_THRESHOLD:
            return 1  # Strong
        elif max_abs > TIER2_THRESHOLD:
            return 2  # Moderate
        else:
            return 3  # Weak

    def _kmeans_abs_corr_api(arr_normed, k, n_init=10, max_iter=300, seed=42):
        """K-Means using absolute correlation: fold sign then Euclidean."""
        n, d = arr_normed.shape
        folded = arr_normed.copy()
        for i in range(n):
            if np.sum(folded[i]) < 0:
                folded[i] = -folded[i]
        norms = np.linalg.norm(folded, axis=1, keepdims=True)
        norms[norms < 1e-9] = 1.0
        folded = folded / norms
        return _numpy_kmeans(folded, k=k, n_init=n_init, max_iter=max_iter, seed=seed)

    def _cluster_ptms_by_trajectory(ptm_list):
        """v11.3: Stratified Clustering (Magnitude Tiers) + Absolute Correlation.

        Algorithm:
          1. Assign each substrate to a Magnitude Tier (Strong/Moderate/Weak)
          2. Within each tier, cluster by absolute-correlation K-Means
          3. Score each sub-cluster independently (Winsorized Mean)
          4. Select dominant cluster across all tiers (with tier bonus)

        Returns list of clusters: [{ptm_keys, size, coherence, ...}].
        """
        valid_keys = []
        raw_vectors = []
        for ptm in ptm_list:
            pk = f"{ptm.get('gene', '').upper()}_{str(ptm.get('position', '')).upper()}"
            ts = ptm_timeseries.get(pk, {})
            if not ts:
                continue
            row = [ts.get(c, 0.0) for c in conditions_sorted]
            if any(v != 0 for v in row):
                valid_keys.append(pk)
                raw_vectors.append(row)
        if not valid_keys:
            return []
        n_subs = len(valid_keys)

        # Fallback: too few substrates or conditions
        if n_subs < MIN_SUBSTRATES_FOR_CLUSTERING or n_conditions < 2:
            coh = _compute_coherence_for_keys(valid_keys)
            return [{"ptm_keys": valid_keys, "cluster_id": 0, "size": n_subs,
                     "coherence": coh, "is_dominant": True, "tier": "mixed"}]

        # ── Step 1: Assign Magnitude Tiers ──
        tiers: dict[int, list[tuple[int, str, list[float]]]] = {1: [], 2: [], 3: []}
        for idx, (pk, vec) in enumerate(zip(valid_keys, raw_vectors)):
            tier = _assign_tier_api(vec)
            tiers[tier].append((idx, pk, vec))

        # ── Step 2: Cluster within each tier ──
        all_clusters = []
        cluster_id_counter = 0
        tier_names = {1: "strong", 2: "moderate", 3: "weak"}
        tier_bonus_map = {1: 2.0, 2: 1.5, 3: 1.0}

        for tier_num in [1, 2, 3]:
            tier_data = tiers[tier_num]
            if not tier_data:
                continue

            tier_keys = [d[1] for d in tier_data]
            tier_vectors = [d[2] for d in tier_data]
            n_tier = len(tier_keys)

            if n_tier < MIN_SUBSTRATES_FOR_CLUSTERING:
                # Too few — single cluster for this tier
                coh = _compute_coherence_for_keys(tier_keys)
                # Compute Winsorized Mean score per condition
                tier_scores = {}
                for c in conditions_sorted:
                    vals = [ptm_timeseries.get(pk, {}).get(c, 0.0) for pk in tier_keys]
                    non_zero = [v for v in vals if v != 0]
                    if len(non_zero) >= 5:
                        arr_v = np.array(non_zero)
                        lo = float(np.percentile(arr_v, WINSORIZE_LOWER))
                        hi = float(np.percentile(arr_v, WINSORIZE_UPPER))
                    else:
                        lo, hi = -1e9, 1e9
                    winsorized = [max(lo, min(hi, v)) for v in vals if v != 0 or abs(v) >= FC_THRESHOLD]
                    tier_scores[c] = round(float(np.mean(winsorized)), 4) if winsorized else 0.0
                peak_c = max(conditions_sorted, key=lambda c: abs(tier_scores.get(c, 0)))
                peak_s = tier_scores.get(peak_c, 0)
                dominance = max(coh, 0.01) * (n_tier ** 0.5) * max(abs(peak_s), 0.01) * tier_bonus_map[tier_num]
                all_clusters.append({
                    "ptm_keys": tier_keys, "cluster_id": cluster_id_counter,
                    "size": n_tier, "coherence": coh, "is_dominant": False,
                    "tier": tier_names[tier_num],
                    "_dominance_score": round(dominance, 4),
                    "_scores": tier_scores, "_peak_condition": peak_c, "_peak_score": peak_s,
                })
                cluster_id_counter += 1
                continue

            # L2-normalize for shape clustering
            arr = np.array(tier_vectors, dtype=np.float64)
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            norms[norms < 1e-9] = 1.0
            arr_normed = arr / norms

            k_tier = min(3, max(2, n_tier // 30))
            k_tier = min(k_tier, n_tier)

            try:
                labels = _kmeans_abs_corr_api(arr_normed, k=k_tier, n_init=10, max_iter=300, seed=42)
            except Exception:
                labels = np.zeros(n_tier, dtype=int)

            # Build sub-clusters
            tier_cluster_map: dict[int, list[str]] = {}
            for idx_l, label in enumerate(labels):
                tier_cluster_map.setdefault(int(label), []).append(tier_keys[idx_l])

            for sub_cid, c_keys in sorted(tier_cluster_map.items()):
                c_size = len(c_keys)
                if c_size < 2:
                    continue
                c_coh = _compute_coherence_for_keys(c_keys)
                # Winsorized Mean score per condition
                c_scores = {}
                for c in conditions_sorted:
                    vals = [ptm_timeseries.get(pk, {}).get(c, 0.0) for pk in c_keys]
                    non_zero = [v for v in vals if v != 0]
                    if len(non_zero) >= 5:
                        arr_v = np.array(non_zero)
                        lo = float(np.percentile(arr_v, WINSORIZE_LOWER))
                        hi = float(np.percentile(arr_v, WINSORIZE_UPPER))
                    else:
                        lo, hi = -1e9, 1e9
                    winsorized = [max(lo, min(hi, v)) for v in vals if abs(v) >= FC_THRESHOLD or v != 0]
                    c_scores[c] = round(float(np.mean(winsorized)), 4) if winsorized else 0.0
                c_peak_c = max(conditions_sorted, key=lambda c: abs(c_scores.get(c, 0)))
                c_peak_s = c_scores.get(c_peak_c, 0)
                dominance = max(c_coh, 0.01) * (c_size ** 0.5) * max(abs(c_peak_s), 0.01) * tier_bonus_map[tier_num]
                all_clusters.append({
                    "ptm_keys": c_keys, "cluster_id": cluster_id_counter,
                    "size": c_size, "coherence": c_coh, "is_dominant": False,
                    "tier": tier_names[tier_num],
                    "_dominance_score": round(dominance, 4),
                    "_scores": c_scores, "_peak_condition": c_peak_c, "_peak_score": c_peak_s,
                })
                cluster_id_counter += 1

        # ── Step 3: Select dominant cluster ──
        if not all_clusters:
            coh = _compute_coherence_for_keys(valid_keys)
            return [{"ptm_keys": valid_keys, "cluster_id": 0, "size": n_subs,
                     "coherence": coh, "is_dominant": True, "tier": "mixed"}]

        best_idx = max(range(len(all_clusters)), key=lambda i: all_clusters[i]["_dominance_score"])
        all_clusters[best_idx]["is_dominant"] = True
        return all_clusters

    # ── Main scoring loop with substrate clustering + Winsorized Mean (v11.3) ──

    kinase_scores = []
    for km in kinase_modules:
        kinase_name = km.get("kinase", "")
        ptms = km.get("ptms", [])
        confidence = km.get("confidence_score", 0.5)

        # v11.3: Cluster substrates by temporal trajectory (Stratified + AbsCorr)
        clusters = _cluster_ptms_by_trajectory(ptms)
        if not clusters:
            continue
        dominant = next((cl for cl in clusters if cl["is_dominant"]), clusters[0])
        dominant_keys = set(dominant["ptm_keys"])

        # v11.3: Use pre-computed _scores from dominant cluster when available
        if "_scores" in dominant:
            scores = dict(dominant["_scores"])
            peak_cond = dominant.get("_peak_condition", "")
            peak_score = dominant.get("_peak_score", 0.0)
        else:
            # Fallback: compute Winsorized Mean from raw PTM data
            _raw_fc: dict[str, list[float]] = {c: [] for c in conditions_sorted}
            for pk in dominant_keys:
                ts = ptm_timeseries.get(pk, {})
                if not ts:
                    continue
                for c in conditions_sorted:
                    fc = ts.get(c, 0.0)
                    if fc != 0 or abs(fc) >= FC_THRESHOLD:
                        _raw_fc[c].append(fc)
            scores = {}
            for c in conditions_sorted:
                vals = _raw_fc[c]
                if len(vals) >= 5:
                    arr_v = np.array(vals)
                    lo = float(np.percentile(arr_v, WINSORIZE_LOWER))
                    hi = float(np.percentile(arr_v, WINSORIZE_UPPER))
                    winsorized = [max(lo, min(hi, v)) for v in vals]
                    scores[c] = round(float(np.mean(winsorized)), 4)
                elif vals:
                    scores[c] = round(float(np.mean(vals)), 4)
                else:
                    scores[c] = 0.0
            if scores:
                peak_cond = max(scores, key=lambda c: abs(scores[c]))
                peak_score = scores[peak_cond]
            else:
                peak_cond = ""
                peak_score = 0.0

        # Legacy up_sums/down_sums for backward compatibility + temporal pattern
        up_sums: dict[str, float] = {c: 0.0 for c in conditions_sorted}
        down_sums: dict[str, float] = {c: 0.0 for c in conditions_sorted}
        up_counts: dict[str, int] = {c: 0 for c in conditions_sorted}
        down_counts: dict[str, int] = {c: 0 for c in conditions_sorted}
        coact_counts: dict[str, int] = {c: 0 for c in conditions_sorted}
        exclusive_sums: dict[str, float] = {c: 0.0 for c in conditions_sorted}
        shared_sums: dict[str, float] = {c: 0.0 for c in conditions_sorted}
        exclusive_counts: dict[str, int] = {c: 0 for c in conditions_sorted}
        shared_counts: dict[str, int] = {c: 0 for c in conditions_sorted}
        tier_up_sums: dict[str, dict[str, float]] = {
            t: {c: 0.0 for c in conditions_sorted} for t in ("de_novo", "regulated", "minor")
        }
        tier_down_sums: dict[str, dict[str, float]] = {
            t: {c: 0.0 for c in conditions_sorted} for t in ("de_novo", "regulated", "minor")
        }
        tier_up_counts: dict[str, dict[str, int]] = {
            t: {c: 0 for c in conditions_sorted} for t in ("de_novo", "regulated", "minor")
        }
        tier_down_counts: dict[str, dict[str, int]] = {
            t: {c: 0 for c in conditions_sorted} for t in ("de_novo", "regulated", "minor")
        }

        # Compute legacy sums from dominant cluster PTMs
        for pk in dominant_keys:
            ts = ptm_timeseries.get(pk, {})
            if not ts:
                continue
            is_exclusive = len(ptm_to_kinases.get(pk, [])) <= 1
            for c in conditions_sorted:
                fc = ts.get(c, 0.0)
                q_val = ptm_qvalues.get(pk, {}).get(c)
                passes_threshold = False
                if q_val is not None and q_val < Q_THRESHOLD:
                    passes_threshold = True
                elif abs(fc) >= FC_THRESHOLD:
                    passes_threshold = True
                if passes_threshold:
                    coact_counts[c] += 1
                    tier = _classify_tier(abs(fc))
                    if fc > 0:
                        up_sums[c] += fc
                        up_counts[c] += 1
                        tier_up_sums[tier][c] += fc
                        tier_up_counts[tier][c] += 1
                    elif fc < 0:
                        down_sums[c] += fc
                        down_counts[c] += 1
                        tier_down_sums[tier][c] += fc
                        tier_down_counts[tier][c] += 1
                    if is_exclusive:
                        exclusive_sums[c] += fc
                        exclusive_counts[c] += 1
                    else:
                        shared_sums[c] += fc
                        shared_counts[c] += 1

        for c in conditions_sorted:
            up_sums[c] = round(up_sums[c], 3)
            down_sums[c] = round(down_sums[c], 3)

        tier_data = {}
        for tier in ("de_novo", "regulated", "minor"):
            tier_data[tier] = {
                "up_sums": {c: round(tier_up_sums[tier][c], 3) for c in conditions_sorted},
                "down_sums": {c: round(tier_down_sums[tier][c], 3) for c in conditions_sorted},
                "up_counts": tier_up_counts[tier],
                "down_counts": tier_down_counts[tier],
            }

        # v11.3: Cluster details — use pre-computed _scores from clusters
        cluster_details = []
        for cl in clusters:
            if "_scores" in cl:
                cl_scores_dict = dict(cl["_scores"])
                cl_peak_cond = cl.get("_peak_condition", "")
                cl_peak_score = cl.get("_peak_score", 0.0)
            else:
                # Fallback: compute from raw PTM values
                cl_scores_dict = {}
                for c in conditions_sorted:
                    c_sum = sum(ptm_timeseries.get(pk, {}).get(c, 0.0) for pk in cl["ptm_keys"])
                    cl_scores_dict[c] = round(c_sum / max(len(cl["ptm_keys"]), 1), 4)
                cl_peak_cond = max(conditions_sorted, key=lambda c: abs(cl_scores_dict.get(c, 0)))
                cl_peak_score = cl_scores_dict.get(cl_peak_cond, 0.0)
            cl_dir = "activation" if cl_peak_score > 0.3 else ("inactivation" if cl_peak_score < -0.3 else "neutral")
            cluster_details.append({
                "cluster_id": cl["cluster_id"],
                "size": cl["size"],
                "scores": cl_scores_dict,
                "coherence": cl["coherence"],
                "peak_condition": cl_peak_cond,
                "peak_score": round(cl_peak_score, 4),
                "direction": cl_dir,
                "is_dominant": cl["is_dominant"],
                "tier": cl.get("tier", "mixed"),
            })

        kinase_scores.append({
            "kinase": kinase_name,
            "scores": scores,
            "up_sums": up_sums,
            "down_sums": down_sums,
            "up_counts": up_counts,
            "down_counts": down_counts,
            "tiers": tier_data,
            "substrate_count": dominant["size"],        # dominant cluster size
            "total_substrates": len(ptms),               # original total
            "confidence": confidence,
            "peak_condition": peak_cond,
            "peak_score": round(peak_score, 4),
            "coact_counts": coact_counts,
            "exclusive_sums": {c: round(v, 3) for c, v in exclusive_sums.items()},
            "shared_sums": {c: round(v, 3) for c, v in shared_sums.items()},
            "exclusive_counts": exclusive_counts,
            "shared_counts": shared_counts,
            "coherence": dominant.get("coherence", 0.0),  # dominant cluster coherence
            "n_clusters": len(clusters),
            "cluster_details": cluster_details,
            # v11.3: Include dominant cluster substrate list
            "substrates": [
                {
                    "ptm_key": pk,
                    "gene": pk.split("_")[0] if "_" in pk else pk,
                    "site": pk.split("_", 1)[1] if "_" in pk else "",
                    "peak_fc": round(float(max(
                        (ptm_timeseries.get(pk, {}).get(c, 0.0) for c in conditions_sorted),
                        key=abs, default=0.0
                    )), 3),
                }
                for pk in dominant["ptm_keys"]
            ],
        })

        # ── v11.3 Multi-pattern: Emit non-dominant clusters as sub-pattern entries ──
        # This allows the frontend to display multiple temporal phases per kinase
        # (e.g., CDK1 early cytoplasmic targets vs CDK1 late nuclear targets)
        if len(clusters) >= 2:
            for cl in clusters:
                if cl["is_dominant"]:
                    continue
                # Only emit sub-patterns with meaningful signal
                if cl["size"] < 3:
                    continue
                if "_scores" in cl:
                    sub_scores = dict(cl["_scores"])
                    sub_peak_cond = cl.get("_peak_condition", "")
                    sub_peak_score = cl.get("_peak_score", 0.0)
                else:
                    sub_scores = {}
                    for c in conditions_sorted:
                        c_vals = [ptm_timeseries.get(pk, {}).get(c, 0.0) for pk in cl["ptm_keys"]]
                        sub_scores[c] = round(float(np.mean(c_vals)) if c_vals else 0.0, 4)
                    sub_peak_cond = max(conditions_sorted, key=lambda c: abs(sub_scores.get(c, 0))) if sub_scores else ""
                    sub_peak_score = sub_scores.get(sub_peak_cond, 0.0)
                # Skip if peak signal is negligible
                if abs(sub_peak_score) < 0.3:
                    continue
                # Auto-label: use actual peak condition as label (e.g., "5min", "12h")
                # Also keep positional category for translocation detection
                cond_idx = conditions_sorted.index(sub_peak_cond) if sub_peak_cond in conditions_sorted else 0
                if cond_idx <= len(conditions_sorted) // 3:
                    sub_label_category = "early_response"
                elif cond_idx >= len(conditions_sorted) * 2 // 3:
                    sub_label_category = "late_response"
                else:
                    sub_label_category = "mid_response"
                sub_label = sub_peak_cond  # Use actual condition name (e.g., "5min", "12h")
                sub_dir = "activation" if sub_peak_score > 0.3 else ("inactivation" if sub_peak_score < -0.3 else "neutral")
                kinase_scores.append({
                    "kinase": f"{kinase_name}_c{cl['cluster_id']}",
                    "parent_kinase": kinase_name,
                    "is_sub_pattern": True,
                    "sub_pattern_label": sub_label,
                    "sub_pattern_category": sub_label_category,  # early/mid/late for translocation detection
                    "scores": sub_scores,
                    "up_sums": {c: 0.0 for c in conditions_sorted},
                    "down_sums": {c: 0.0 for c in conditions_sorted},
                    "up_counts": {c: 0 for c in conditions_sorted},
                    "down_counts": {c: 0 for c in conditions_sorted},
                    "tiers": {},
                    "substrate_count": cl["size"],
                    "total_substrates": len(ptms),
                    "confidence": confidence * 0.7,  # slightly lower confidence for sub-patterns
                    "peak_condition": sub_peak_cond,
                    "peak_score": round(sub_peak_score, 4),
                    "coact_counts": {c: 0 for c in conditions_sorted},
                    "exclusive_sums": {c: 0.0 for c in conditions_sorted},
                    "shared_sums": {c: 0.0 for c in conditions_sorted},
                    "exclusive_counts": {c: 0 for c in conditions_sorted},
                    "shared_counts": {c: 0 for c in conditions_sorted},
                    "coherence": cl.get("coherence", 0.0),
                    "n_clusters": 1,
                    "cluster_details": [{
                        "cluster_id": cl["cluster_id"],
                        "size": cl["size"],
                        "scores": sub_scores,
                        "coherence": cl.get("coherence", 0.0),
                        "peak_condition": sub_peak_cond,
                        "peak_score": round(sub_peak_score, 4),
                        "direction": sub_dir,
                        "is_dominant": True,
                        "tier": cl.get("tier", "mixed"),
                    }],
                    "direction": sub_dir,
                    # v11.3: Include substrate list for frontend display
                    "substrates": [
                        {
                            "ptm_key": pk,
                            "gene": pk.split("_")[0] if "_" in pk else pk,
                            "site": pk.split("_", 1)[1] if "_" in pk else "",
                            "peak_fc": round(float(max(
                                (ptm_timeseries.get(pk, {}).get(c, 0.0) for c in conditions_sorted),
                                key=abs, default=0.0
                            )), 3),
                        }
                        for pk in cl["ptm_keys"]
                    ],
                })

    # ── Peak Synchronization ──
    peak_groups: dict[str, list[str]] = {}
    for ks_entry in kinase_scores:
        pc = ks_entry.get("peak_condition", "")
        if pc:
            peak_groups.setdefault(pc, []).append(ks_entry["kinase"])
    peak_sync = {}
    for cond_name, kinase_list in peak_groups.items():
        if len(kinase_list) >= 3:
            peak_sync[cond_name] = {"kinases": kinase_list, "count": len(kinase_list)}

    # ── Co-wave group assignment ──
    cowave_groups = []
    if len(kinase_scores) >= 3 and len(conditions_sorted) >= 2:
        score_matrix = []
        valid_kinase_names = []
        for ks_entry in kinase_scores:
            # v11.3: Exclude sub-patterns from co-wave correlation (they inherit parent group)
            if ks_entry.get("is_sub_pattern"):
                continue
            row = [ks_entry["scores"].get(c, 0.0) for c in conditions_sorted]
            if any(abs(v) > 0.3 for v in row):
                score_matrix.append(row)
                valid_kinase_names.append(ks_entry["kinase"])
        if len(valid_kinase_names) >= 3:
            arr = np.array(score_matrix)
            try:
                corr = np.corrcoef(arr)
                visited: set[int] = set()
                group_id = 0
                for i in range(len(valid_kinase_names)):
                    if i in visited:
                        continue
                    group = [i]
                    visited.add(i)
                    for j in range(i + 1, len(valid_kinase_names)):
                        if j not in visited and not np.isnan(corr[i][j]) and corr[i][j] >= 0.7:
                            group.append(j)
                            visited.add(j)
                    if len(group) >= 2:
                        _grp_kinases = [valid_kinase_names[idx] for idx in group]
                        _peak_counts: dict[str, int] = {}
                        for _gk in _grp_kinases:
                            _ks_match = next((ks for ks in kinase_scores if ks["kinase"] == _gk), None)
                            if _ks_match and _ks_match.get("peak_condition"):
                                _pc = _ks_match["peak_condition"]
                                _peak_counts[_pc] = _peak_counts.get(_pc, 0) + 1
                        _dominant_peak = max(_peak_counts, key=_peak_counts.get) if _peak_counts else ""
                        cowave_groups.append({
                            "group_id": group_id,
                            "kinases": _grp_kinases,
                            "size": len(group),
                            "mean_correlation": round(float(np.mean(
                                [corr[a][b] for a in group for b in group if a != b and not np.isnan(corr[a][b])]
                            )), 3) if len(group) > 1 else 1.0,
                            "dominant_peak": _dominant_peak,
                        })
                        group_id += 1
            except Exception:
                pass

    # Annotate each kinase with its co-wave group
    kinase_to_group: dict[str, int] = {}
    for grp in cowave_groups:
        for k in grp["kinases"]:
            kinase_to_group[k] = grp["group_id"]
    for ks_entry in kinase_scores:
        if ks_entry.get("is_sub_pattern"):
            # Sub-patterns inherit parent's co-wave group
            ks_entry["cowave_group"] = kinase_to_group.get(ks_entry.get("parent_kinase", ""), -1)
        else:
            ks_entry["cowave_group"] = kinase_to_group.get(ks_entry["kinase"], -1)

    # ── Activation / Inactivation classification (Sum-based) ──
    for ks_entry in kinase_scores:
        peak = ks_entry.get("peak_score", 0)
        peak_cond = ks_entry.get("peak_condition", "")
        peak_coact = ks_entry.get("coact_counts", {}).get(peak_cond, 0)
        if peak > 0 and peak_coact >= 2:
            ks_entry["direction"] = "activation"
        elif peak < 0 and peak_coact >= 2:
            ks_entry["direction"] = "inactivation"
        else:
            ks_entry["direction"] = "neutral"

    # ── Temporal Pattern Classification ──────────────────────────────────────
    # Detect notable temporal patterns for each kinase across conditions.
    # Works with any number of conditions (not hardcoded to 4 timepoints).
    # Uses net signal per condition: up_sum + down_sum (signed)
    SIGNAL_THRESHOLD = 1.0  # minimum |net signal| to consider "active"
    EMERGENCE_RATIO = 5.0   # fold-change threshold for sudden appearance

    n_conds = len(conditions_sorted)
    for ks_entry in kinase_scores:
        up_s = ks_entry.get("up_sums", {})
        dn_s = ks_entry.get("down_sums", {})
        # Net signal per condition (positive = net up, negative = net down)
        net_signals = []
        for c in conditions_sorted:
            net = (up_s.get(c, 0) or 0) + (dn_s.get(c, 0) or 0)
            net_signals.append(net)
        # Absolute magnitude per condition
        abs_signals = [abs(s) for s in net_signals]
        max_abs = max(abs_signals) if abs_signals else 0

        patterns: list[str] = []

        if max_abs < SIGNAL_THRESHOLD:
            patterns.append("inactive")
            ks_entry["temporal_pattern"] = patterns
            continue

        # 1. Check active positions (which conditions have signal)
        active_mask = [a >= SIGNAL_THRESHOLD for a in abs_signals]
        first_active = next((i for i, v in enumerate(active_mask) if v), None)
        last_active = next((i for i, v in reversed(list(enumerate(active_mask))) if v), None)
        n_active = sum(active_mask)

        # 2. Direction per active condition
        directions = []  # +1, -1, or 0
        for s in net_signals:
            if s >= SIGNAL_THRESHOLD:
                directions.append(1)
            elif s <= -SIGNAL_THRESHOLD:
                directions.append(-1)
            else:
                directions.append(0)

        # ── Pattern: Sustained Activation / Inactivation ──
        if n_active == n_conds and all(d == 1 for d in directions):
            patterns.append("sustained_activation")
        elif n_active == n_conds and all(d == -1 for d in directions):
            patterns.append("sustained_inactivation")

        # ── Pattern: Late Onset (first half inactive, second half active) ──
        if first_active is not None and n_conds >= 3:
            half = n_conds // 2
            if first_active >= half and all(not active_mask[i] for i in range(half)):
                patterns.append("late_onset")

        # ── Pattern: Early Only (first half active, second half inactive) ──
        if last_active is not None and n_conds >= 3:
            half = (n_conds + 1) // 2  # ceiling
            if last_active < half and all(not active_mask[i] for i in range(half, n_conds)):
                patterns.append("early_only")

        # ── Pattern: Sudden Emergence (signal jumps from ~0 to large) ──
        for i in range(1, n_conds):
            prev_abs = abs_signals[i - 1]
            curr_abs = abs_signals[i]
            if prev_abs < SIGNAL_THRESHOLD * 0.5 and curr_abs >= SIGNAL_THRESHOLD:
                if curr_abs >= EMERGENCE_RATIO * max(prev_abs, 0.1):
                    patterns.append(f"emergence_at_{conditions_sorted[i]}")
                    break  # only first emergence

        # ── Pattern: Sudden Disappearance (signal drops from large to ~0) ──
        for i in range(1, n_conds):
            prev_abs = abs_signals[i - 1]
            curr_abs = abs_signals[i]
            if prev_abs >= SIGNAL_THRESHOLD and curr_abs < SIGNAL_THRESHOLD * 0.3:
                patterns.append(f"disappearance_at_{conditions_sorted[i]}")
                break

        # ── Pattern: Transient Spike (one condition >> neighbors) ──
        for i in range(n_conds):
            if abs_signals[i] < SIGNAL_THRESHOLD:
                continue
            neighbors = []
            if i > 0:
                neighbors.append(abs_signals[i - 1])
            if i < n_conds - 1:
                neighbors.append(abs_signals[i + 1])
            if neighbors:
                max_neighbor = max(neighbors)
                if abs_signals[i] >= 3.0 * max(max_neighbor, 0.1):
                    patterns.append(f"spike_at_{conditions_sorted[i]}")
                    break

        # ── Pattern: Direction Reversal (up→down or down→up) ──
        active_dirs = [(i, d) for i, d in enumerate(directions) if d != 0]
        if len(active_dirs) >= 2:
            for j in range(1, len(active_dirs)):
                if active_dirs[j][1] != active_dirs[j - 1][1]:
                    reversal_cond = conditions_sorted[active_dirs[j][0]]
                    patterns.append(f"reversal_at_{reversal_cond}")
                    break

        # ── Pattern: Progressive Amplification (monotonically increasing |signal|) ──
        if n_active >= 3:
            active_abs = [abs_signals[i] for i in range(n_conds) if active_mask[i]]
            if all(active_abs[k] <= active_abs[k + 1] for k in range(len(active_abs) - 1)):
                if active_abs[-1] >= 2.0 * active_abs[0]:
                    patterns.append("progressive_amplification")

        # ── Pattern: Progressive Decay (monotonically decreasing |signal|) ──
        if n_active >= 3:
            active_abs = [abs_signals[i] for i in range(n_conds) if active_mask[i]]
            if all(active_abs[k] >= active_abs[k + 1] for k in range(len(active_abs) - 1)):
                if active_abs[0] >= 2.0 * active_abs[-1]:
                    patterns.append("progressive_decay")

        if not patterns:
            patterns.append("mixed")

        ks_entry["temporal_pattern"] = patterns

    # Sort by peak_score descending
    kinase_scores.sort(key=lambda x: abs(x["peak_score"]), reverse=True)

    # Filter: only include kinases with ≥2 substrates
    kinase_scores_filtered = [ks for ks in kinase_scores if ks["substrate_count"] >= 2]
    if len(kinase_scores_filtered) < 5 and len(kinase_scores) >= 5:
        kinase_scores_filtered = kinase_scores[:20]

    # Collect unique patterns for frontend filter UI
    all_patterns: set[str] = set()
    for ks in kinase_scores_filtered:
        all_patterns.update(ks.get("temporal_pattern", []))

    # ── v11.3: Translocation Auto-Detection ──────────────────────────────────
    # For multi-pattern kinases, compare early vs late cluster substrate genes.
    # If early cluster genes are predominantly cytoplasmic and late cluster genes
    # are predominantly nuclear, flag as "potential_translocation".
    # This uses cached GO localization data if available.
    translocation_candidates: list[dict] = []
    if order.substrate_go_localization:
        go_cache = order.substrate_go_localization.get("gene_localizations", {})
        if go_cache:
            # Group sub-patterns by parent kinase
            parent_sub_map: dict[str, list[dict]] = {}
            for ks_entry in kinase_scores_filtered:
                if ks_entry.get("is_sub_pattern") and ks_entry.get("parent_kinase"):
                    parent_sub_map.setdefault(ks_entry["parent_kinase"], []).append(ks_entry)

            for parent, subs in parent_sub_map.items():
                early_subs = [s for s in subs if s.get("sub_pattern_category") == "early_response"]
                late_subs = [s for s in subs if s.get("sub_pattern_category") == "late_response"]
                if not early_subs or not late_subs:
                    continue

                # Get substrate genes for early and late clusters
                # Find parent module to get member genes per cluster
                parent_mod = None
                for km in kinase_modules:
                    if km.get("kinase", "").upper() == parent.upper():
                        parent_mod = km
                        break
                if not parent_mod:
                    continue

                # Get all substrate genes for this kinase
                # ptms is a list of dicts: [{gene, position}, ...]
                all_genes = list(set(
                    (p.get("gene", "") if isinstance(p, dict) else p.split("_")[0]).upper()
                    for p in parent_mod.get("ptms", [])
                    if (p.get("gene", "") if isinstance(p, dict) else p)
                ))

                # Count GO CC terms for all genes
                cytoplasm_count = 0
                nucleus_count = 0
                for gene in all_genes:
                    locs = go_cache.get(gene, [])
                    if "cytoplasm" in locs:
                        cytoplasm_count += 1
                    if "nucleus" in locs:
                        nucleus_count += 1

                total = len(all_genes)
                if total < 4:
                    continue

                # Heuristic: if both cytoplasm and nucleus are represented,
                # and early peaks before late, it's a translocation candidate
                early_indices = [
                    conditions_sorted.index(s["peak_condition"])
                    for s in early_subs if s.get("peak_condition") in conditions_sorted
                ]
                late_indices = [
                    conditions_sorted.index(s["peak_condition"])
                    for s in late_subs if s.get("peak_condition") in conditions_sorted
                ]
                if not early_indices or not late_indices:
                    continue
                early_peak_idx = min(early_indices)
                late_peak_idx = max(late_indices)

                if (early_peak_idx < late_peak_idx and
                    cytoplasm_count >= 2 and nucleus_count >= 2 and
                    (cytoplasm_count + nucleus_count) >= total * 0.4):
                    translocation_candidates.append({
                        "kinase": parent,
                        "early_peak": conditions_sorted[early_peak_idx],
                        "late_peak": conditions_sorted[late_peak_idx],
                        "cytoplasm_genes": cytoplasm_count,
                        "nucleus_genes": nucleus_count,
                        "total_genes": total,
                        "hypothesis": "potential_nuclear_translocation",
                        "description": f"{parent} shows early cytoplasmic substrate activity "
                                       f"({conditions_sorted[early_peak_idx]}) followed by late nuclear "
                                       f"substrate activity ({conditions_sorted[late_peak_idx]}), "
                                       f"suggesting kinase nuclear translocation.",
                    })
                    # Tag the parent entry
                    for ks_entry in kinase_scores_filtered:
                        if ks_entry.get("kinase") == parent:
                            ks_entry["translocation_flag"] = "potential_nuclear_translocation"
                            break

    # Save to DB
    result_data = {
        "kinase_scores": kinase_scores_filtered,
        "conditions": conditions_sorted,
        "peak_sync": peak_sync,
        "cowave_groups": cowave_groups,
        "available_patterns": sorted(all_patterns),
        "translocation_candidates": translocation_candidates,
        "scoring_method": "stratified_winsorized_mean_v11.3",
        "scoring_threshold": {"q_value": Q_THRESHOLD, "fc_abs": FC_THRESHOLD},
        "_cache_hash": cache_hash,
        "computed_at": _dt.utcnow().isoformat(),
    }
    order.kinase_activity_heatmap = result_data
    await db.commit()

    return {**result_data, "_cached": False}


# ─────────────────────────────────────────────────────────────────────────────
# Treatment text typo-detection endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/validate-treatment")
async def validate_treatment(
    body: dict = Body(...),
):
    """
    Given a treatment text, return spelling suggestions for any tokens that
    closely resemble known ligand names but are not exact matches.

    Request body: { "treatment": "1 nM of Irsin" }
    Response:     { "suggestions": [ { "original_token": "Irsin",
                                        "suggested": "Irisin",
                                        "canonical": "irisin",
                                        "confidence": "high",
                                        "distance": 1 } ] }
    """
    from app.services.ligand_receptor_db import suggest_corrections_for_treatment

    treatment_text = (body.get("treatment") or "").strip()
    if not treatment_text:
        return {"suggestions": []}

    suggestions = suggest_corrections_for_treatment(treatment_text, max_suggestions=5)
    return {"suggestions": suggestions}


# ─────────────────────────────────────────────────────────────────────────────
# GO Cellular Component Localization endpoint (v11.3)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{order_id}/substrate-go-localization")
async def substrate_go_localization(
    order_id: int,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Fetch GO Cellular Component annotations for substrate genes from UniProt.

    This enables the Heatmap ↔ GO Localization dashboard to show where
    substrates are located in the cell (nucleus, cytoplasm, membrane, etc.),
    supporting translocation hypothesis generation.

    Request body:
      - genes: [str]  (list of gene names to query)
      - force_refresh: bool (default false)

    Response:
      - gene_localizations: {GENE: ["nucleus", "cytoplasm", ...]}
      - summary: {term: count}
      - _cached: bool
    """
    import httpx
    from datetime import datetime as _dt

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    await _check_order_access_async(order, user, db)

    genes = body.get("genes", [])
    force_refresh = body.get("force_refresh", False)

    if not genes:
        raise HTTPException(status_code=400, detail="No genes provided")

    # Check cache
    if not force_refresh and order.substrate_go_localization:
        cached = order.substrate_go_localization
        cached_genes = set(cached.get("gene_localizations", {}).keys())
        requested_genes = set(g.upper() for g in genes)
        # If all requested genes are already cached, return immediately
        if requested_genes.issubset(cached_genes):
            # Filter to only requested genes
            filtered = {g: cached["gene_localizations"].get(g.upper(), []) for g in genes}
            summary: dict[str, int] = {}
            for locs in filtered.values():
                for loc in locs:
                    summary[loc] = summary.get(loc, 0) + 1
            return {
                "gene_localizations": filtered,
                "summary": dict(sorted(summary.items(), key=lambda x: -x[1])),
                "_cached": True,
            }

    # Determine species/organism
    species_lower = (order.species or "human").lower()
    uniprot_organism_id = (
        "10090" if "mouse" in species_lower or "mus" in species_lower
        else "9606" if "human" in species_lower or "homo" in species_lower
        else "10116" if "rat" in species_lower or "rattus" in species_lower
        else ""
    )

    UNIPROT_BASE = "https://rest.uniprot.org/uniprotkb"

    # Canonical GO CC term normalization
    GO_CC_KEYWORDS = {
        "nucleus": ["nucleus", "nuclear", "nucleoplasm", "nucleolus", "chromatin"],
        "cytoplasm": ["cytoplasm", "cytosol"],
        "membrane": ["membrane", "plasma membrane", "cell membrane"],
        "mitochondrion": ["mitochondri"],
        "endoplasmic reticulum": ["endoplasmic reticulum", "er membrane"],
        "golgi apparatus": ["golgi"],
        "cytoskeleton": ["cytoskeleton", "actin", "microtubule"],
        "extracellular": ["extracellular", "secreted"],
        "centrosome": ["centrosome", "centriole"],
        "ribosome": ["ribosom"],
        "lysosome": ["lysosom", "endosom"],
        "peroxisome": ["peroxisom"],
    }

    def _normalize_go_cc(raw_locations: list[str]) -> list[str]:
        """Normalize raw GO CC / subcellular location strings to canonical terms."""
        normalized: set[str] = set()
        for raw in raw_locations:
            raw_lower = raw.lower()
            for canonical, keywords in GO_CC_KEYWORDS.items():
                if any(kw in raw_lower for kw in keywords):
                    normalized.add(canonical)
                    break
            else:
                # Keep original if no match (but cleaned up)
                cleaned = raw.strip().rstrip(".").lower()
                if cleaned and len(cleaned) > 2:
                    normalized.add(cleaned)
        return sorted(normalized)

    async def _fetch_go_cc_for_gene(client: httpx.AsyncClient, gene: str) -> list[str]:
        """Fetch GO Cellular Component terms for a single gene from UniProt."""
        raw_locations: list[str] = []
        try:
            # Search UniProt for the gene
            query = f"gene_exact:{gene}"
            if uniprot_organism_id:
                query += f"+AND+organism_id:{uniprot_organism_id}"
            query += "+AND+reviewed:true"

            resp = await client.get(
                f"{UNIPROT_BASE}/search",
                params={
                    "query": query,
                    "fields": "accession,cc_subcellular_location,xref_go",
                    "format": "json",
                    "size": "1",
                },
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            entries = data.get("results", [])
            if not entries:
                return []
            entry = entries[0]

            # Extract from subcellularLocations comment
            for comment in entry.get("comments", []):
                if comment.get("commentType") == "SUBCELLULAR LOCATION":
                    for sub_loc in comment.get("subcellularLocations", []):
                        loc_val = sub_loc.get("location", {}).get("value", "")
                        if loc_val:
                            raw_locations.append(loc_val)

            # Extract from GO cross-references (Cellular Component = C)
            for xref in entry.get("uniProtKBCrossReferences", []):
                if xref.get("database") == "GO":
                    go_id = xref.get("id", "")
                    props = xref.get("properties", [])
                    for prop in props:
                        if prop.get("key") == "GoTerm" and prop.get("value", "").startswith("C:"):
                            # "C:nucleus" → "nucleus"
                            term = prop["value"][2:]
                            raw_locations.append(term)

        except Exception:
            pass

        return _normalize_go_cc(raw_locations)

    # Batch fetch with concurrency limit
    import asyncio
    gene_localizations: dict[str, list[str]] = {}
    unique_genes = list(set(g.upper() for g in genes))

    # Use existing cache as base
    if order.substrate_go_localization:
        gene_localizations = dict(order.substrate_go_localization.get("gene_localizations", {}))

    # Only fetch genes not already cached (unless force_refresh)
    genes_to_fetch = unique_genes if force_refresh else [
        g for g in unique_genes if g not in gene_localizations
    ]

    if genes_to_fetch:
        BATCH_SIZE = 10
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            for i in range(0, len(genes_to_fetch), BATCH_SIZE):
                batch = genes_to_fetch[i:i + BATCH_SIZE]
                tasks = [_fetch_go_cc_for_gene(client, g) for g in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for gene, result in zip(batch, results):
                    if isinstance(result, Exception):
                        gene_localizations[gene] = []
                    else:
                        gene_localizations[gene] = result
                # Small delay between batches to avoid rate limiting
                if i + BATCH_SIZE < len(genes_to_fetch):
                    await asyncio.sleep(0.5)

    # Build summary for requested genes only
    summary: dict[str, int] = {}
    filtered_localizations: dict[str, list[str]] = {}
    for g in unique_genes:
        locs = gene_localizations.get(g, [])
        filtered_localizations[g] = locs
        for loc in locs:
            summary[loc] = summary.get(loc, 0) + 1

    # Save full cache to DB (accumulative)
    cache_data = {
        "gene_localizations": gene_localizations,
        "fetched_at": _dt.utcnow().isoformat(),
    }
    order.substrate_go_localization = cache_data
    await db.commit()

    return {
        "gene_localizations": filtered_localizations,
        "summary": dict(sorted(summary.items(), key=lambda x: -x[1])),
        "_cached": False,
    }
