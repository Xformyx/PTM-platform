import base64
import hashlib
import hmac as _hmac
import json
import logging
import mimetypes
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.system_setting import SystemSetting
from app.models.user import User

router = APIRouter(prefix="/settings", tags=["settings"])
logger = logging.getLogger("ptm-platform.settings")

_settings = get_settings()
_FILE_SHARE_DIR = Path(_settings.FILE_SHARE_DIR)


def _safe_filename(name: str) -> str:
    """Sanitize filename to prevent path traversal."""
    name = os.path.basename(name)
    name = re.sub(r"[^\w.\-]", "_", name)
    return name or "file"


def _ensure_share_dir() -> Path:
    _FILE_SHARE_DIR.mkdir(parents=True, exist_ok=True)
    return _FILE_SHARE_DIR


class EmailNotificationsUpdate(BaseModel):
    email_notifications_enabled: bool


@router.get("/email-notifications")
async def get_email_notifications(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's email notification preference."""
    if getattr(user, "id", 0) == 0:
        return {"email_notifications_enabled": True}
    result = await db.execute(select(User).where(User.id == user.id))
    u = result.scalar_one_or_none()
    if not u:
        return {"email_notifications_enabled": True}
    return {"email_notifications_enabled": getattr(u, "email_notifications_enabled", True)}


@router.patch("/email-notifications")
async def update_email_notifications(
    body: EmailNotificationsUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's email notification preference."""
    if getattr(user, "id", 0) == 0:
        return {"email_notifications_enabled": body.email_notifications_enabled}
    result = await db.execute(select(User).where(User.id == user.id))
    u = result.scalar_one_or_none()
    if not u:
        return {"email_notifications_enabled": body.email_notifications_enabled}
    u.email_notifications_enabled = body.email_notifications_enabled
    await db.commit()
    await db.refresh(u)
    return {"email_notifications_enabled": u.email_notifications_enabled}


# ── System Settings (key-value store) ────────────────────────────────────


class SystemSettingUpdate(BaseModel):
    settings: dict[str, str]


@router.get("/system")
async def get_system_settings(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return all system settings grouped by category."""
    result = await db.execute(select(SystemSetting))
    rows = result.scalars().all()
    settings: list[dict] = []
    for s in rows:
        settings.append({
            "key": s.setting_key,
            "value": s.setting_value,
            "description": s.description,
            "category": s.category,
            "value_type": s.value_type,
            "updated_at": s.updated_at.isoformat() + "Z" if s.updated_at else None,
        })
    return {"settings": settings}


@router.patch("/system")
async def update_system_settings(
    body: SystemSettingUpdate,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Update one or more system settings.
    Expects: { "settings": { "KEY": "VALUE", ... } }
    """
    if getattr(user, "role", "viewer") not in ("admin", "analyst"):
        raise HTTPException(status_code=403, detail="Only admin or analyst can change system settings")

    updated: list[str] = []
    for key, value in body.settings.items():
        result = await db.execute(
            select(SystemSetting).where(SystemSetting.setting_key == key)
        )
        setting = result.scalar_one_or_none()
        if setting is None:
            logger.warning(f"Unknown system setting key: {key}")
            continue
        setting.setting_value = str(value)
        updated.append(key)

    if updated:
        await db.commit()
        logger.info(f"System settings updated: {updated}")

    result = await db.execute(select(SystemSetting))
    rows = result.scalars().all()
    settings = [
        {
            "key": s.setting_key,
            "value": s.setting_value,
            "description": s.description,
            "category": s.category,
            "value_type": s.value_type,
            "updated_at": s.updated_at.isoformat() + "Z" if s.updated_at else None,
        }
        for s in rows
    ]
    return {"settings": settings, "updated": updated}


# ── Admin File Share ──────────────────────────────────────────────────────


def _require_admin(user):
    if getattr(user, "role", "viewer") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


# ── Download Token Helpers ────────────────────────────────────────────────
# Short-lived (5 min) HMAC-signed token so large files can be downloaded
# via a plain <a href> without Authorization headers in the browser.

_DL_TOKEN_TTL = 300  # seconds


def _make_dl_token(filename: str, user_id: int) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"f": filename, "u": user_id, "exp": int(time.time()) + _DL_TOKEN_TTL}).encode()
    ).decode()
    sig = _hmac.new(_settings.JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_dl_token(token: str) -> str | None:
    """Returns the filename if the token is valid, None otherwise."""
    try:
        payload, sig = token.rsplit(".", 1)
        expected = _hmac.new(_settings.JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload))
        if data["exp"] < time.time():
            return None
        return str(data["f"])
    except Exception:
        return None


# ── Chunked Upload Helpers ────────────────────────────────────────────────

CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB


def _sessions_dir() -> Path:
    d = _FILE_SHARE_DIR / ".upload_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_dir(upload_id: str) -> Path:
    safe_id = re.sub(r"[^\w-]", "", upload_id)
    return _sessions_dir() / safe_id


def _read_session(upload_id: str) -> dict | None:
    meta = _session_dir(upload_id) / "meta.json"
    if not meta.exists():
        return None
    try:
        return json.loads(meta.read_text())
    except Exception:
        return None


def _write_session(upload_id: str, data: dict) -> None:
    d = _session_dir(upload_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(data))


class CreateDirectoryRequest(BaseModel):
    path: str   # relative path within file_share, e.g. "mouse_samples" or "2025/run1"


@router.post("/directories", status_code=201)
async def create_directory(body: CreateDirectoryRequest, user=Depends(get_current_user)):
    """Create a directory inside the file share."""
    _require_admin(user)
    share_dir = _ensure_share_dir()
    # Sanitize: allow only safe path components
    parts = [re.sub(r"[^\w.\-]", "_", p) for p in Path(body.path).parts if p not in ("", ".", "..")]
    if not parts:
        raise HTTPException(400, detail="Invalid directory path")
    target = share_dir.joinpath(*parts)
    if target.exists():
        return {"path": str(target.relative_to(share_dir)), "already_existed": True}
    target.mkdir(parents=True, exist_ok=True)
    return {"path": str(target.relative_to(share_dir)), "already_existed": False}


@router.get("/files")
async def list_files(path: str = "", user=Depends(get_current_user)):
    """List files and subdirectories in the file share at the given relative path."""
    _require_admin(user)
    share_dir = _ensure_share_dir()

    # Resolve and validate path stays within share_dir
    if path:
        parts = [p for p in Path(path).parts if p not in ("", ".", "..")]
        current = share_dir.joinpath(*parts) if parts else share_dir
    else:
        current = share_dir

    try:
        current = current.resolve()
        share_dir = share_dir.resolve()
        if not str(current).startswith(str(share_dir)):
            raise HTTPException(400, detail="Path outside file share")
    except Exception:
        raise HTTPException(400, detail="Invalid path")

    if not current.is_dir():
        raise HTTPException(404, detail="Directory not found")

    rel_base = current.relative_to(share_dir)
    files = []
    dirs = []
    for p in sorted(current.iterdir()):
        if p.name.startswith("."):
            continue
        if p.is_dir():
            dirs.append({
                "name": p.name,
                "path": str(rel_base / p.name) if str(rel_base) != "." else p.name,
            })
        elif p.is_file():
            stat = p.stat()
            mime, _ = mimetypes.guess_type(p.name)
            files.append({
                "name": p.name,
                "path": str(rel_base / p.name) if str(rel_base) != "." else p.name,
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
                "mime_type": mime or "application/octet-stream",
            })
    return {
        "current_path": str(rel_base) if str(rel_base) != "." else "",
        "dirs": dirs,
        "files": files,
    }


@router.post("/files")
async def upload_file(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Upload a file to the admin file share directory."""
    _require_admin(user)
    share_dir = _ensure_share_dir()

    safe_name = _safe_filename(file.filename or "upload")
    dest = share_dir / safe_name

    # If file already exists, add numeric suffix
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        counter = 1
        while dest.exists():
            dest = share_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    async with aiofiles.open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            await f.write(chunk)

    stat = dest.stat()
    logger.info(f"File share upload: {dest.name} ({stat.st_size} bytes) by user {getattr(user, 'id', 0)}")
    return {"name": dest.name, "size": stat.st_size}


@router.get("/files/{filename}/dl-token")
async def get_download_token(filename: str, user=Depends(get_current_user)):
    """Issue a short-lived signed download token for the given file (admin only)."""
    _require_admin(user)
    share_dir = _ensure_share_dir()
    safe_name = _safe_filename(filename)
    if not (share_dir / safe_name).is_file():
        raise HTTPException(status_code=404, detail="File not found")
    token = _make_dl_token(safe_name, getattr(user, "id", 0))
    return {"token": token, "expires_in": _DL_TOKEN_TTL}


@router.get("/files/{filename}/dl")
async def download_file_by_token(
    filename: str,
    token: str = Query(...),
):
    """Token-based download — no Authorization header needed (browser native download)."""
    verified = _verify_dl_token(token)
    if not verified:
        raise HTTPException(status_code=401, detail="Invalid or expired download token")
    safe_name = _safe_filename(filename)
    if verified != safe_name:
        raise HTTPException(status_code=403, detail="Token filename mismatch")
    share_dir = _ensure_share_dir()
    file_path = share_dir / safe_name
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    mime, _ = mimetypes.guess_type(file_path.name)
    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type=mime or "application/octet-stream",
    )


@router.get("/files/{filename}")
async def download_file(filename: str, user=Depends(get_current_user)):
    """Download a file from the admin file share directory."""
    _require_admin(user)
    share_dir = _ensure_share_dir()

    safe_name = _safe_filename(filename)
    file_path = share_dir / safe_name

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    mime, _ = mimetypes.guess_type(file_path.name)
    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type=mime or "application/octet-stream",
    )


@router.delete("/files/{filename}")
async def delete_file(filename: str, user=Depends(get_current_user)):
    """Delete a file from the admin file share directory."""
    _require_admin(user)
    share_dir = _ensure_share_dir()

    safe_name = _safe_filename(filename)
    file_path = share_dir / safe_name

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    file_path.unlink()
    logger.info(f"File share delete: {safe_name} by user {getattr(user, 'id', 0)}")
    return {"deleted": safe_name}


# ── Chunked Upload Endpoints ──────────────────────────────────────────────


class ChunkInitRequest(BaseModel):
    filename: str
    total_size: int
    total_chunks: int
    chunk_size: int = CHUNK_SIZE


@router.post("/files/chunks/init")
async def init_chunked_upload(
    body: ChunkInitRequest,
    user=Depends(get_current_user),
):
    """Create a new chunked upload session. Returns upload_id."""
    _require_admin(user)
    upload_id = str(uuid.uuid4())
    safe_name = _safe_filename(body.filename)
    session = {
        "upload_id": upload_id,
        "filename": safe_name,
        "total_size": body.total_size,
        "total_chunks": body.total_chunks,
        "chunk_size": body.chunk_size,
        "received_chunks": [],
        "status": "uploading",
    }
    _write_session(upload_id, session)
    logger.info(f"Chunked upload init: {upload_id} ({safe_name}, {body.total_chunks} chunks)")
    return {"upload_id": upload_id, "total_chunks": body.total_chunks}


@router.get("/files/chunks/{upload_id}/status")
async def get_chunk_upload_status(
    upload_id: str,
    user=Depends(get_current_user),
):
    """Return the current progress of a chunked upload session."""
    _require_admin(user)
    session = _read_session(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")
    received = len(session["received_chunks"])
    total = session["total_chunks"]
    return {
        "upload_id": upload_id,
        "filename": session["filename"],
        "total_size": session["total_size"],
        "received_chunks": received,
        "total_chunks": total,
        "pct": int(received / total * 100) if total > 0 else 0,
        "status": session["status"],
    }


# IMPORTANT: finalize must be registered BEFORE the catch-all chunk_index route,
# otherwise FastAPI will try to parse "finalize" as int chunk_index → 422.
@router.post("/files/chunks/{upload_id}/finalize")
async def finalize_chunked_upload(
    upload_id: str,
    user=Depends(get_current_user),
):
    """Merge all chunks and move the assembled file to the share directory."""
    _require_admin(user)
    session = _read_session(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")

    total = session["total_chunks"]
    received_set = set(session["received_chunks"])
    missing = [i for i in range(total) if i not in received_set]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing chunks: {missing[:10]}{'…' if len(missing) > 10 else ''}",
        )

    session["status"] = "finalizing"
    _write_session(upload_id, session)

    share_dir = _ensure_share_dir()
    dest = share_dir / session["filename"]
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        counter = 1
        while dest.exists():
            dest = share_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    session_dir = _session_dir(upload_id)
    async with aiofiles.open(dest, "wb") as out:
        for i in range(total):
            chunk_path = session_dir / f"chunk_{i:05d}"
            async with aiofiles.open(chunk_path, "rb") as inp:
                while data := await inp.read(1024 * 1024):
                    await out.write(data)

    shutil.rmtree(session_dir, ignore_errors=True)
    stat = dest.stat()
    logger.info(f"Chunked upload complete: {dest.name} ({stat.st_size} bytes) by user {getattr(user, 'id', 0)}")
    return {"name": dest.name, "size": stat.st_size}


@router.post("/files/chunks/{upload_id}/{chunk_index}")
async def upload_chunk(
    upload_id: str,
    chunk_index: int,
    chunk: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Upload a single chunk for the given session."""
    _require_admin(user)
    session = _read_session(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")
    if session["status"] != "uploading":
        raise HTTPException(status_code=400, detail=f"Session is {session['status']}")
    if chunk_index < 0 or chunk_index >= session["total_chunks"]:
        raise HTTPException(status_code=400, detail="Invalid chunk index")

    chunk_path = _session_dir(upload_id) / f"chunk_{chunk_index:05d}"
    async with aiofiles.open(chunk_path, "wb") as f:
        while data := await chunk.read(1024 * 1024):
            await f.write(data)

    if chunk_index not in session["received_chunks"]:
        session["received_chunks"].append(chunk_index)
    _write_session(upload_id, session)

    received = len(session["received_chunks"])
    return {
        "upload_id": upload_id,
        "chunk_index": chunk_index,
        "received_chunks": received,
        "total_chunks": session["total_chunks"],
    }


@router.delete("/files/chunks/{upload_id}")
async def cancel_chunked_upload(
    upload_id: str,
    user=Depends(get_current_user),
):
    """Cancel and clean up a chunked upload session."""
    _require_admin(user)
    session_dir = _session_dir(upload_id)
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="Upload session not found")
    shutil.rmtree(session_dir, ignore_errors=True)
    logger.info(f"Chunked upload cancelled: {upload_id} by user {getattr(user, 'id', 0)}")
    return {"cancelled": upload_id}
