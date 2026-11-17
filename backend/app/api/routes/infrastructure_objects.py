from fastapi import APIRouter, Depends, status

from app.api.deps import SessionDep, require_auth
from app.core.responses import ok
from app.schemas.common import Envelope
from app.schemas.infrastructure_object import (
    InfrastructureObjectCreate,
    InfrastructureObjectRead,
    InfrastructureObjectUpdate,
)
from app.services import object_service

router = APIRouter(
    prefix="/infrastructure-objects",
    tags=["Объекты инфраструктуры"],
    dependencies=[Depends(require_auth)],
)


@router.get("", response_model=Envelope[list[InfrastructureObjectRead]])
async def list_objects(session: SessionDep):
    return ok(await object_service.list_objects(session))


@router.get("/{object_id}", response_model=Envelope[InfrastructureObjectRead])
async def get_object(object_id: int, session: SessionDep):
    return ok(await object_service.get_object(session, object_id))


@router.post(
    "",
    response_model=Envelope[InfrastructureObjectRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_object(payload: InfrastructureObjectCreate, session: SessionDep):
    return ok(await object_service.create_object(session, payload))


@router.put("/{object_id}", response_model=Envelope[InfrastructureObjectRead])
async def update_object(
    object_id: int,
    payload: InfrastructureObjectUpdate,
    session: SessionDep,
):
    return ok(await object_service.update_object(session, object_id, payload))


@router.delete("/{object_id}", response_model=Envelope[bool])
async def delete_object(object_id: int, session: SessionDep):
    await object_service.delete_object(session, object_id)
    return ok(True)
