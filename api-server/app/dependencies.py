from typing import Optional

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User


class InternalUser:
    """Pseudo-user when auth is disabled."""

    id: int = 0
    email: str = "internal@ptm-platform.local"
    name: str = "Internal User"
    role: str = "admin"
    is_active: bool = True


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User | InternalUser:
    if not settings.AUTH_ENABLED:
        return InternalUser()

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )

    return await _resolve_user_from_token(auth_header.removeprefix("Bearer "), db)


async def _resolve_user_from_token(
    raw_token: str,
    db: AsyncSession,
) -> User | InternalUser:
    """Validate a raw JWT string and return the corresponding User."""
    payload = decode_access_token(raw_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


async def get_sse_user(
    request: Request,
    token: Optional[str] = Query(None, description="JWT for EventSource (cannot send headers)"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User | InternalUser:
    """Auth dependency for SSE endpoints.

    The browser EventSource API does not support custom headers, so we accept
    the JWT both as the standard ``Authorization: Bearer`` header **and** as a
    ``?token=`` query parameter.  The header takes precedence when present.
    """
    if not settings.AUTH_ENABLED:
        return InternalUser()

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return await _resolve_user_from_token(auth_header.removeprefix("Bearer "), db)

    if token:
        return await _resolve_user_from_token(token, db)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authorization (provide Authorization header or ?token= query param)",
    )


def require_sse_role(*roles: str):
    """Like require_role, but for EventSource endpoints (header or ?token=)."""
    async def checker(user=Depends(get_sse_user)):
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(roles)}",
            )
        return user

    return checker


def require_role(*roles: str):
    async def checker(user=Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(roles)}",
            )
        return user

    return checker
