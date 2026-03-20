from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/settings", tags=["settings"])


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
