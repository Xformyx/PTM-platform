from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.notification import Notification
from app.models.user import User

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List notifications for current user, newest first."""
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    notifications = result.scalars().all()
    return [
        {
            "id": n.id,
            "order_id": n.order_id,
            "notification_type": n.notification_type,
            "title": n.title,
            "message": n.message,
            "read_at": n.read_at.isoformat() + "Z" if n.read_at else None,
            "created_at": n.created_at.isoformat() + "Z",
        }
        for n in notifications
    ]


@router.get("/unread-count")
async def unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return count of unread notifications."""
    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
        )
    )
    count = result.scalar() or 0
    return {"count": count}


@router.patch("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a notification as read."""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    n = result.scalar_one_or_none()
    if not n:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    n.read_at = datetime.utcnow()
    await db.commit()
    return {"ok": True}


@router.post("/mark-all-read")
async def mark_all_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark all notifications as read."""
    from sqlalchemy import update

    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.utcnow())
    )
    await db.commit()
    return {"ok": True}


@router.delete("")
async def delete_all_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete all notifications for the current user."""
    await db.execute(delete(Notification).where(Notification.user_id == user.id))
    await db.commit()
    return {"ok": True}
