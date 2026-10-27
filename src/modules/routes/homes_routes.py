from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Response

from modules.auth.dependencies import CurrentUser, Repository
from modules.auth.middleware import HomeAdminUser, MasterUser
from modules.controller import homes_controller
from modules.schemas.auth_schemas import UserProfile
from modules.schemas.homes_schemas import (
    CreateHomeRequest,
    HomeProfile,
    TransferHomePrimaryRequest,
)
from modules.schemas.users_schemas import AddHomeMemberRequest
from modules.service.idempotency_service import execute_idempotently

router = APIRouter(prefix="/homes", tags=["homes"])
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=200),
]


@router.get("", response_model=list[HomeProfile])
async def list_homes(
    actor: CurrentUser,
    repository: Repository,
) -> list[HomeProfile]:
    return await homes_controller.list_homes(actor, repository)


@router.post("", response_model=HomeProfile, status_code=201)
async def create_home(
    payload: CreateHomeRequest,
    actor: CurrentUser,
    repository: Repository,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> HomeProfile:
    async def operation() -> tuple[HomeProfile, int]:
        return await homes_controller.create_home(payload, actor, repository), 201

    return await execute_idempotently(
        key=idempotency_key,
        scope=f"home-create:{actor.id}",
        request_model=payload,
        response_model=HomeProfile,
        response=response,
        repository=repository,
        operation=operation,
    )


@router.get("/{home_id}/users", response_model=list[UserProfile])
async def list_home_members(
    home_id: UUID,
    _: HomeAdminUser,
    repository: Repository,
) -> list[UserProfile]:
    return await homes_controller.list_home_members(home_id, repository)


@router.post("/{home_id}/users", response_model=UserProfile, status_code=201)
async def add_home_member(
    home_id: UUID,
    payload: AddHomeMemberRequest,
    actor: HomeAdminUser,
    repository: Repository,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> UserProfile:
    async def operation() -> tuple[UserProfile, int]:
        result = await homes_controller.add_home_member(home_id, payload, repository)
        return result, 201

    return await execute_idempotently(
        key=idempotency_key,
        scope=f"home-member:{actor.id}:{home_id}",
        request_model=payload,
        response_model=UserProfile,
        response=response,
        repository=repository,
        operation=operation,
    )


@router.delete("/{home_id}/users/{user_id}", status_code=204, response_class=Response)
async def remove_home_member(
    home_id: UUID,
    user_id: UUID,
    actor: HomeAdminUser,
    repository: Repository,
) -> Response:
    await homes_controller.remove_home_member(home_id, user_id, actor, repository)
    return Response(status_code=204)


@router.patch("/{home_id}/primary", response_model=HomeProfile)
async def transfer_home_primary(
    home_id: UUID,
    payload: TransferHomePrimaryRequest,
    actor: MasterUser,
    repository: Repository,
) -> HomeProfile:
    return await homes_controller.transfer_home_primary(
        home_id,
        payload.user_id,
        actor,
        repository,
    )
