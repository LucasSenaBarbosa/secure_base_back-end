from uuid import UUID

from fastapi import Response

from modules.repository.supabase_repository import SupabaseRepository
from modules.schemas.auth_schemas import UserProfile
from modules.service import users_service


async def list_users(repository: SupabaseRepository) -> list[UserProfile]:
    return await users_service.list_users(repository)


async def delete_user(
    user_id: UUID,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> Response:
    await users_service.remove_user(user_id, actor, repository)
    return Response(status_code=204)
