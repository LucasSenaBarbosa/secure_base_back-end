from uuid import UUID

from modules.repository.supabase_repository import SupabaseRepository
from modules.schemas.auth_schemas import Role, UserProfile
from modules.schemas.homes_schemas import CreateHomeRequest, HomeProfile
from modules.service import users_service


async def list_homes(
    actor: UserProfile,
    repository: SupabaseRepository,
) -> list[HomeProfile]:
    rows = await repository.list_homes(actor.id, is_master=actor.role == Role.MASTER)
    homes = []
    for row in rows:
        is_primary = UUID(str(row["primary_user_id"])) == actor.id
        role = Role.MASTER if actor.role == Role.MASTER else (
            Role.PRIMARY if is_primary else Role.MEMBER
        )
        homes.append(
            HomeProfile(
                id=row["id"],
                name=row["name"],
                primary_user_id=row["primary_user_id"],
                role=role,
            )
        )
    return homes


async def create_home(
    payload: CreateHomeRequest,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> HomeProfile:
    row = await repository.create_home(payload.name, actor.id)
    role = Role.MASTER if actor.role == Role.MASTER else Role.PRIMARY
    return HomeProfile(
        id=row["id"],
        name=row["name"],
        primary_user_id=row["primary_user_id"],
        role=role,
    )


async def list_home_members(
    home_id: UUID,
    repository: SupabaseRepository,
) -> list[UserProfile]:
    return await users_service.list_home_members(home_id, repository)


async def add_home_member(
    home_id: UUID,
    email: str,
    repository: SupabaseRepository,
) -> UserProfile:
    return await users_service.add_home_member(
        home_id,
        email,
        repository,
    )


async def remove_home_member(
    home_id: UUID,
    user_id: UUID,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> None:
    await users_service.remove_home_member(home_id, user_id, actor, repository)


async def transfer_home_primary(
    home_id: UUID,
    new_primary_id: UUID,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> HomeProfile:
    row = await repository.transfer_home_primary(home_id, new_primary_id)
    role = Role.MASTER if actor.role == Role.MASTER else Role.PRIMARY
    return HomeProfile(
        id=row["id"],
        name=row["name"],
        primary_user_id=row["primary_user_id"],
        role=role,
    )
