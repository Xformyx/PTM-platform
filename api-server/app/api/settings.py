import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.system_setting import SystemSetting
from app.models.user import User

router = APIRouter(prefix="/settings", tags=["settings"])
logger = logging.getLogger("ptm-platform.settings")


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
