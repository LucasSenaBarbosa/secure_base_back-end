from uuid import UUID

from modules.repository.supabase_repository import SupabaseRepository
from modules.schemas.auth_schemas import UserProfile
from modules.schemas.homes_schemas import CreateHomeRequest, HomeProfile
from modules.schemas.users_schemas import AddHomeMemberRequest
from modules.service import homes_service


async def list_homes(
    actor: UserProfile,
    repository: SupabaseRepository,
) -> list[HomeProfile]:
    return await homes_service.list_homes(actor, repository)


async def create_home(
    payload: CreateHomeRequest,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> HomeProfile:
    return await homes_service.create_home(payload, actor, repository)


async def list_home_members(
    home_id: UUID,
    repository: SupabaseRepository,
) -> list[UserProfile]:
    return await homes_service.list_home_members(home_id, repository)


async def add_home_member(
    home_id: UUID,
    payload: AddHomeMemberRequest,
    repository: SupabaseRepository,
) -> UserProfile:
    return await homes_service.add_home_member(
        home_id,
        str(payload.email),
        repository,
    )


async def remove_home_member(
    home_id: UUID,
    user_id: UUID,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> None:
    await homes_service.remove_home_member(home_id, user_id, actor, repository)


async def transfer_home_primary(
    home_id: UUID,
    new_primary_id: UUID,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> HomeProfile:
    return await homes_service.transfer_home_primary(
        home_id,
        new_primary_id,
        actor,
        repository,
    )
