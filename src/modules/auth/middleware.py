from typing import Annotated
from uuid import UUID

from fastapi import Depends

from modules.auth.dependencies import Repository, get_current_user
from modules.schemas.auth_schemas import Role, UserProfile
from shared.errors.problem_details import Problem


async def require_master(
    user: Annotated[UserProfile, Depends(get_current_user)],
) -> UserProfile:
    if user.role != Role.MASTER:
        raise Problem(
            403,
            "FORBIDDEN",
            "Acesso negado",
            "Esta operação exige perfil de administrador master.",
        )
    return user


MasterUser = Annotated[UserProfile, Depends(require_master)]


async def require_home_admin(
    home_id: UUID,
    user: Annotated[UserProfile, Depends(get_current_user)],
    repository: Repository,
) -> UserProfile:
    if user.role == Role.MASTER:
        return user
    home = await repository.get_home(home_id)
    if home is None:
        raise Problem(404, "HOME_NOT_FOUND", "Não encontrada", "A residência não existe.")
    if UUID(str(home["primary_user_id"])) != user.id:
        raise Problem(
            403,
            "FORBIDDEN",
            "Acesso negado",
            "Esta operação exige o perfil primary desta residência.",
        )
    return user


HomeAdminUser = Annotated[UserProfile, Depends(require_home_admin)]
