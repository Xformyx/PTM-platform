import logging
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.dependencies import get_current_user, require_role
from app.models.login_attempt import LoginAttempt
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("ptm-platform.auth")

DEFAULT_PASSWORD = "ptm1234"


def _extract_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _resolve_location(ip: str) -> str | None:
    """Best-effort IP geolocation via ip-api.com (free, no key)."""
    if ip in ("127.0.0.1", "::1", "unknown") or ip.startswith(("10.", "172.", "192.168.")):
        return "Local network"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    parts = [data.get("city"), data.get("regionName"), data.get("country")]
                    return ", ".join(p for p in parts if p)
    except Exception:
        pass
    return None


async def _record_login(
    db: AsyncSession, *, email: str, user_id: int | None, user_name: str | None,
    reason: str, login_status: str, request: Request,
) -> None:
    ip = _extract_ip(request)
    ua = request.headers.get("user-agent", "")[:512]
    location = await _resolve_location(ip)
    db.add(LoginAttempt(
        email=email, user_id=user_id, user_name=user_name,
        reason=reason, status=login_status,
        ip_address=ip, location=location, user_agent=ua,
    ))
    await db.commit()


def _user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "must_change_password": u.must_change_password,
        "email_notifications_enabled": getattr(u, "email_notifications_enabled", True),
    }


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class CreateUserRequest(BaseModel):
    email: str
    name: str
    role: str = "analyst"  # "admin" or "analyst"


class UpdateUserRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


@router.post("/login")
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    email = "admin@ptm.local" if body.email.strip().lower() == "admin" else body.email.strip()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        await _record_login(
            db, email=email, user_id=user.id, user_name=user.name,
            reason="disabled_account", login_status="blocked", request=request,
        )
        logger.warning(f"Disabled user login attempt: {email} from {_extract_ip(request)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인 오류가 발생합니다",
        )

    await _record_login(
        db, email=email, user_id=user.id, user_name=user.name,
        reason="login", login_status="success", request=request,
    )

    token = create_access_token({"sub": str(user.id)})
    logger.info(f"User logged in: {user.email} (role={user.role})")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_dict(user),
    }


@router.get("/me")
async def get_me(user=Depends(get_current_user)):
    return _user_dict(user)


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    if len(body.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 6 characters",
        )
    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the current password",
        )

    # Re-fetch mutable object from session
    result = await db.execute(select(User).where(User.id == user.id))
    db_user = result.scalar_one()
    db_user.password_hash = hash_password(body.new_password)
    db_user.must_change_password = False
    await db.commit()
    await db.refresh(db_user)
    logger.info(f"Password changed for user: {db_user.email}")
    return {"message": "Password changed successfully", "user": _user_dict(db_user)}


@router.get("/users")
async def list_users(
    user=Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at.asc()))
    users = result.scalars().all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "role": u.role,
            "is_active": u.is_active,
            "must_change_password": u.must_change_password,
            "created_at": u.created_at.isoformat() + "Z",
        }
        for u in users
    ]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    current_user=Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    if body.role not in ("admin", "analyst", "viewer"):
        raise HTTPException(status_code=400, detail="Invalid role. Must be admin, analyst, or viewer")
    if not _EMAIL_RE.match(body.email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = User(
        email=body.email,
        password_hash=hash_password(DEFAULT_PASSWORD),
        name=body.name,
        role=body.role,
        must_change_password=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    logger.info(f"New user created: {new_user.email} (role={new_user.role}) by admin {current_user.email}")
    return {
        "id": new_user.id,
        "email": new_user.email,
        "name": new_user.name,
        "role": new_user.role,
        "is_active": new_user.is_active,
        "must_change_password": new_user.must_change_password,
    }


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    current_user=Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if body.name is not None:
        target.name = body.name
    if body.role is not None:
        if body.role not in ("admin", "analyst", "viewer"):
            raise HTTPException(status_code=400, detail="Invalid role")
        target.role = body.role
    if body.is_active is not None:
        target.is_active = body.is_active
    if body.password is not None:
        if len(body.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        target.password_hash = hash_password(body.password)
        target.must_change_password = True

    await db.commit()
    await db.refresh(target)
    return {
        "id": target.id,
        "email": target.email,
        "name": target.name,
        "role": target.role,
        "is_active": target.is_active,
        "must_change_password": target.must_change_password,
    }


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_user=Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(target)
    await db.commit()


def _attempt_dict(r: LoginAttempt) -> dict:
    return {
        "id": r.id,
        "email": r.email,
        "user_id": r.user_id,
        "user_name": r.user_name,
        "status": r.status,
        "reason": r.reason,
        "ip_address": r.ip_address,
        "location": r.location,
        "user_agent": r.user_agent,
        "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
    }


@router.get("/login-attempts")
async def list_login_attempts(
    user=Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
    user_id: int | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = 50,
):
    """Return recent login attempts. Optionally filter by user_id or status."""
    q = select(LoginAttempt)
    if user_id is not None:
        q = q.where(LoginAttempt.user_id == user_id)
    if status_filter:
        q = q.where(LoginAttempt.status == status_filter)
    q = q.order_by(desc(LoginAttempt.created_at)).limit(min(limit, 200))
    result = await db.execute(q)
    return [_attempt_dict(r) for r in result.scalars().all()]
