from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.openapi_docs import BEARER_SCHEME_DESCRIPTION, BEARER_SCHEME_NAME
from config.settings import Settings, get_settings
from modules.repository.supabase_repository import SupabaseRepository
from modules.schemas.auth_schemas import UserProfile
from modules.service.auth_service import get_authenticated_profile
from shared.errors.problem_details import Problem

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name=BEARER_SCHEME_NAME,
    bearerFormat="JWT",
    description=BEARER_SCHEME_DESCRIPTION,
)


def get_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SupabaseRepository:
    return SupabaseRepository(settings)


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    repository: Annotated[SupabaseRepository, Depends(get_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserProfile:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise Problem(
            401,
            "AUTHENTICATION_REQUIRED",
            "Não autenticado",
            "Envie um token de acesso válido.",
        )
    return await get_authenticated_profile(credentials.credentials, repository, settings)


CurrentUser = Annotated[UserProfile, Depends(get_current_user)]
Repository = Annotated[SupabaseRepository, Depends(get_repository)]
