import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.dependencies import get_current_user, require_role
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("ptm-platform.auth")

DEFAULT_PASSWORD = "ptm1234"


def _user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "must_change_password": u.must_change_password,
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
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    # Allow "Admin" shorthand to resolve to the default admin account
    email = "admin@ptm.local" if body.email.strip().lower() == "admin" else body.email.strip()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
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
