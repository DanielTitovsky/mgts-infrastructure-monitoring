"""Общие зависимости FastAPI."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import decode_token
from app.db.session import get_session
from app.models.user import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(request: Request, session: SessionDep) -> User | None:
    """Пользователь из заголовка `Authorization: Bearer <token>` (если он есть)."""
    header = request.headers.get("Authorization", "")
    scheme, _, raw_token = header.partition(" ")
    token = raw_token.strip()

    if scheme.lower() != "bearer" or not token:
        return None

    payload = decode_token(token, raise_on_error=False)
    if payload is None:
        return None

    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        return None

    return await session.get(User, user_id)


CurrentUser = Annotated[User | None, Depends(get_current_user)]


async def require_auth(user: CurrentUser) -> User | None:
    """Проверяет токен, если защита включена через `AUTH_REQUIRED=true`."""
    if settings.auth_required and user is None:
        raise AppError(401, "Требуется авторизация", "Войдите в систему, чтобы продолжить.")
    return user


AuthGuard = Annotated[User | None, Depends(require_auth)]
