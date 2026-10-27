from uuid import UUID

from fastapi import APIRouter, Response

from modules.auth.dependencies import Repository
from modules.auth.middleware import MasterUser
from modules.controller import users_controller
from modules.schemas.auth_schemas import UserProfile

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserProfile])
async def list_users(
    _: MasterUser,
    repository: Repository,
) -> list[UserProfile]:
    return await users_controller.list_users(repository)


@router.delete("/{user_id}", status_code=204, response_class=Response)
async def delete_user(
    user_id: UUID,
    actor: MasterUser,
    repository: Repository,
) -> Response:
    return await users_controller.delete_user(user_id, actor, repository)
