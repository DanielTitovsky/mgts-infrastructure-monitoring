"""Бизнес-логика объектов инфраструктуры."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.infrastructure_object import InfrastructureObject
from app.models.status import Status
from app.schemas.infrastructure_object import (
    InfrastructureObjectCreate,
    InfrastructureObjectUpdate,
)


async def list_objects(session: AsyncSession) -> list[InfrastructureObject]:
    result = await session.scalars(
        select(InfrastructureObject).order_by(InfrastructureObject.id)
    )
    return list(result)


async def get_object(session: AsyncSession, object_id: int) -> InfrastructureObject:
    obj = await session.get(InfrastructureObject, object_id)
    if obj is None:
        raise AppError(404, "Объект не найден", f"Объект с id={object_id} не существует.")
    return obj


async def create_object(
    session: AsyncSession,
    payload: InfrastructureObjectCreate,
) -> InfrastructureObject:
    await _ensure_status_exists(session, payload.status_id)

    obj = InfrastructureObject(**payload.model_dump())
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return obj


async def update_object(
    session: AsyncSession,
    object_id: int,
    payload: InfrastructureObjectUpdate,
) -> InfrastructureObject:
    obj = await get_object(session, object_id)
    changes = payload.model_dump(exclude_unset=True)

    if "status_id" in changes:
        await _ensure_status_exists(session, changes["status_id"])

    for field, value in changes.items():
        setattr(obj, field, value)

    await session.commit()
    await session.refresh(obj)
    return obj


async def delete_object(session: AsyncSession, object_id: int) -> None:
    obj = await get_object(session, object_id)
    await session.delete(obj)
    await session.commit()


async def _ensure_status_exists(session: AsyncSession, status_id: int | None) -> None:
    if status_id is None:
        return
    if await session.get(Status, status_id) is None:
        raise AppError(400, "Статус не найден", f"Нельзя указать несуществующий статус id={status_id}.")
