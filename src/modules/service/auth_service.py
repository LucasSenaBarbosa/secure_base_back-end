import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from config.settings import Settings
from modules.auth.security import (
    decode_access_token,
    hash_password,
    hash_refresh_token,
    issue_access_token,
    issue_refresh_token,
    verify_password,
)
from modules.repository.supabase_repository import SupabaseRepository
from modules.schemas.auth_schemas import (
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    UserProfile,
)
from shared.errors.problem_details import Problem


async def login(
    payload: LoginRequest,
    repository: SupabaseRepository,
    settings: Settings,
) -> tuple[LoginResponse, str]:
    account = await repository.get_account_by_email(str(payload.email).casefold())
    password_is_valid = await asyncio.to_thread(
        verify_password,
        payload.password,
        account.get("password_hash") if account else None,
    )
    if account is None or not password_is_valid:
        raise _invalid_credentials()

    profile = await repository.get_profile(UUID(account["id"]))
    refresh_token, token_hash = issue_refresh_token()
    family_id = uuid4()
    await repository.create_refresh_session(
        user_id=profile.id,
        family_id=family_id,
        token_hash=token_hash,
        auth_version=int(account["auth_version"]),
        expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=settings.refresh_token_expiry_seconds),
    )
    access_token, expires_in = issue_access_token(
        settings,
        profile.id,
        int(account["auth_version"]),
        family_id,
    )
    return (
        LoginResponse(
            access_token=access_token,
            expires_in=expires_in,
            user=profile,
            csrf_token=secrets.token_urlsafe(32),
        ),
        refresh_token,
    )


async def refresh_session(
    refresh_token: str,
    repository: SupabaseRepository,
    settings: Settings,
) -> tuple[RefreshResponse, str]:
    old_hash = hash_refresh_token(refresh_token)
    new_token, new_hash = issue_refresh_token()
    rotated = await repository.rotate_refresh_session(old_hash, new_hash)
    if rotated is None:
        raise Problem(401, "INVALID_REFRESH_TOKEN", "Sessão expirada", "Entre novamente.")
    account = await repository.get_account(rotated["user_id"])
    if account is None or account.get("password_hash") is None:
        raise Problem(401, "INVALID_REFRESH_TOKEN", "Sessão expirada", "Entre novamente.")
    if int(account["auth_version"]) != rotated["auth_version"]:
        await repository.revoke_refresh_session(new_hash)
        raise Problem(401, "INVALID_REFRESH_TOKEN", "Sessão expirada", "Entre novamente.")
    profile = repository.to_profile(account)
    access_token, expires_in = issue_access_token(
        settings,
        profile.id,
        int(account["auth_version"]),
        rotated["family_id"],
    )
    return (
        RefreshResponse(
            access_token=access_token,
            expires_in=expires_in,
            user=profile,
            csrf_token=secrets.token_urlsafe(32),
        ),
        new_token,
    )


async def logout(refresh_token: str | None, repository: SupabaseRepository) -> None:
    if refresh_token:
        await repository.revoke_refresh_session(hash_refresh_token(refresh_token))


async def register(
    payload: RegisterRequest,
    repository: SupabaseRepository,
) -> tuple[RegisterResponse, Literal[200, 201]]:
    email = str(payload.email).casefold()
    existing = await repository.get_account_by_email(email)
    if existing is not None:
        if existing.get("password_hash") is None:
            password_hash = await asyncio.to_thread(hash_password, payload.password)
            updated = await repository.update_account(
                UUID(str(existing["id"])),
                {
                    "full_name": payload.name.strip(),
                    "password_hash": password_hash,
                    "invitation_token_hash": None,
                    "invitation_expires_at": None,
                    "auth_version": int(existing["auth_version"]) + 1,
                },
                filters={"password_hash": "is.null"},
            )
            if updated is None:
                raise _account_already_exists()
            return (
                RegisterResponse(message="Conta ativada. Você já pode entrar."),
                200,
            )
        raise _account_already_exists()

    password_hash = await asyncio.to_thread(hash_password, payload.password)
    try:
        await repository.create_account(
            email=email,
            name=payload.name.strip(),
            password_hash=password_hash,
        )
    except Problem as exc:
        if exc.code == "ACCOUNT_CONFLICT":
            raise _account_already_exists() from exc
        raise

    return (
        RegisterResponse(message="Conta criada. Você já pode entrar."),
        201,
    )


async def change_password(
    user: UserProfile,
    payload: PasswordChangeRequest,
    repository: SupabaseRepository,
) -> None:
    account = await repository.get_account(user.id)
    if account is None or account.get("password_hash") is None:
        raise _invalid_credentials()
    is_valid = await asyncio.to_thread(
        verify_password,
        payload.current_password,
        account.get("password_hash"),
    )
    if not is_valid:
        raise Problem(
            400,
            "INVALID_CURRENT_PASSWORD",
            "Senha atual inválida",
            "Confira a senha atual e tente novamente.",
        )
    new_hash = await asyncio.to_thread(hash_password, payload.new_password)
    updated = await repository.update_account(
        user.id,
        {
            "password_hash": new_hash,
            "auth_version": int(account["auth_version"]) + 1,
        },
        filters={"auth_version": f"eq.{account['auth_version']}"},
    )
    if updated is None:
        raise Problem(
            409,
            "PASSWORD_UPDATE_CONFLICT",
            "Conflito",
            "A conta foi alterada. Entre novamente e tente outra vez.",
        )
    await repository.revoke_user_refresh_sessions(user.id)


async def get_authenticated_profile(
    access_token: str,
    repository: SupabaseRepository,
    settings: Settings,
) -> UserProfile:
    user_id, token_version, session_id = decode_access_token(settings, access_token)
    account = await repository.get_account(user_id)
    if (
        account is None
        or account.get("password_hash") is None
        or int(account["auth_version"]) != token_version
        or not await repository.is_refresh_family_active(session_id)
    ):
        raise Problem(
            401,
            "INVALID_ACCESS_TOKEN",
            "Não autenticado",
            "A sessão é inválida ou expirou.",
        )
    return repository.to_profile(account)


def _invalid_credentials() -> Problem:
    return Problem(
        401,
        "INVALID_CREDENTIALS",
        "Não foi possível entrar",
        "E-mail ou senha inválidos.",
    )


def _account_already_exists() -> Problem:
    return Problem(
        409,
        "ACCOUNT_ALREADY_EXISTS",
        "Conta já cadastrada",
        "Já existe uma conta com este endereço de e-mail.",
    )
