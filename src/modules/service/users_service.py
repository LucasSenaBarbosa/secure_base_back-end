from uuid import UUID

from modules.repository.supabase_repository import SupabaseRepository
from modules.schemas.auth_schemas import Role, UserProfile
from shared.errors.problem_details import Problem


async def list_users(repository: SupabaseRepository) -> list[UserProfile]:
    return await repository.list_profiles()


async def remove_user(
    user_id: UUID,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> None:
    if user_id == actor.id:
        raise Problem(
            409,
            "SELF_DELETION_FORBIDDEN",
            "Conflito",
            "Não é permitido remover a própria conta.",
        )
    target = await repository.get_profile(user_id)
    if target.role == Role.MASTER:
        raise Problem(
            409,
            "MASTER_DELETION_FORBIDDEN",
            "Conflito",
            "Não é permitido remover uma conta master.",
        )
    if target.role == Role.PRIMARY and actor.role != Role.MASTER:
        raise Problem(
            409,
            "ADMIN_DELETION_FORBIDDEN",
            "Conflito",
            "Somente um administrador master pode remover outra conta administradora.",
        )
    if await repository.user_owns_homes(user_id):
        raise Problem(
            409,
            "HOME_OWNER_DELETION_FORBIDDEN",
            "Conflito",
            "Transfira ou remova as residências antes de remover seu administrador.",
        )
    await repository.delete_user(user_id)


async def add_home_member(
    home_id: UUID,
    email: str,
    repository: SupabaseRepository,
) -> UserProfile:
    home = await repository.get_home(home_id)
    if home is None:
        raise Problem(404, "HOME_NOT_FOUND", "Não encontrada", "A residência não existe.")
    existing = await repository.get_account_by_email(email.casefold())
    if existing is None:
        raise Problem(
            404,
            "USER_NOT_FOUND",
            "Conta não encontrada",
            "A pessoa precisa criar a própria conta antes de ser associada à residência.",
        )
    if str(home["primary_user_id"]) == str(existing["id"]):
        raise Problem(
            409,
            "ACCOUNT_CONFLICT",
            "Conflito",
            "O administrador da residência já pertence a ela.",
        )

    if existing.get("password_hash") is None:
        raise Problem(
            409,
            "ACCOUNT_PENDING",
            "Conta pendente",
            "A pessoa precisa concluir o cadastro com uma senha antes de entrar nesta "
            "residência.",
        )
    user_id = UUID(str(existing["id"]))
    await repository.add_home_member(home_id, user_id)
    profile = repository.to_profile(existing)
    return profile.model_copy(
        update={"role": Role.MASTER if profile.role == Role.MASTER else Role.MEMBER}
    )


async def list_home_members(
    home_id: UUID,
    repository: SupabaseRepository,
) -> list[UserProfile]:
    return await repository.list_home_members(home_id)


async def remove_home_member(
    home_id: UUID,
    user_id: UUID,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> None:
    home = await repository.get_home(home_id)
    if home is None:
        raise Problem(404, "HOME_NOT_FOUND", "Não encontrada", "A residência não existe.")
    if UUID(str(home["primary_user_id"])) == user_id:
        raise Problem(
            409,
            "HOME_PRIMARY_REMOVAL_FORBIDDEN",
            "Conflito",
            "O administrador principal não pode ser removido desta residência.",
        )
    target = await repository.get_profile(user_id)
    if target.role == Role.MASTER and actor.role != Role.MASTER:
        raise Problem(
            409,
            "MASTER_REMOVAL_FORBIDDEN",
            "Conflito",
            "Somente um administrador master pode remover outro master da residência.",
        )
    await repository.remove_home_member(home_id, user_id)
