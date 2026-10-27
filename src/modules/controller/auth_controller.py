from typing import Literal

from config.settings import Settings
from modules.repository.supabase_repository import SupabaseRepository
from modules.schemas.auth_schemas import (
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    RegisterRequest,
    RegisterResponse,
    UserProfile,
)
from modules.service.auth_service import (
    change_password,
    login,
    logout,
    refresh_session,
    register,
)
from shared.errors.problem_details import Problem


async def sign_up(
    payload: RegisterRequest,
    repository: SupabaseRepository,
) -> tuple[RegisterResponse, Literal[200, 201]]:
    return await register(payload, repository)


async def update_password(
    user: UserProfile,
    payload: PasswordChangeRequest,
    repository: SupabaseRepository,
) -> None:
    if payload.current_password == payload.new_password:
        raise Problem(
            422,
            "PASSWORD_UNCHANGED",
            "Senha inválida",
            "A nova senha deve ser diferente da senha atual.",
        )
    await change_password(user, payload, repository)


async def get_me(user: UserProfile) -> UserProfile:
    return user


async def sign_in(
    payload: LoginRequest,
    repository: SupabaseRepository,
    settings: Settings,
) -> tuple[LoginResponse, str]:
    return await login(payload, repository, settings)


async def refresh(
    token: str,
    repository: SupabaseRepository,
    settings: Settings,
) -> tuple[LoginResponse, str]:
    return await refresh_session(token, repository, settings)


async def sign_out(token: str | None, repository: SupabaseRepository) -> None:
    await logout(token, repository)
