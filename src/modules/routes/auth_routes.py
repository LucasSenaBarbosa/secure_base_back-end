import secrets
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response

from config.settings import Settings, get_settings
from modules.auth.dependencies import CurrentUser, Repository
from modules.controller.auth_controller import get_me as handle_get_me
from modules.controller.auth_controller import refresh as handle_refresh
from modules.controller.auth_controller import sign_in as handle_sign_in
from modules.controller.auth_controller import sign_out as handle_sign_out
from modules.controller.auth_controller import sign_up as handle_sign_up
from modules.controller.auth_controller import update_password as handle_update_password
from modules.schemas.auth_schemas import (
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    UserProfile,
)
from modules.service.idempotency_service import execute_idempotently
from shared.errors.problem_details import Problem

router = APIRouter(prefix="/auth", tags=["auth"])
RefreshCookie = "securebase-refresh"
CsrfCookie = "securebase-csrf"
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=200),
]


@router.post("/login", response_model=LoginResponse)
async def sign_in(
    payload: LoginRequest,
    repository: Repository,
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> LoginResponse:
    result, refresh_token = await handle_sign_in(payload, repository, settings)
    _set_session_cookies(response, refresh_token, result.csrf_token, settings)
    return result


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: Request,
    response: Response,
    repository: Repository,
    settings: Annotated[Settings, Depends(get_settings)],
    refresh_token: Annotated[str | None, Cookie(alias=RefreshCookie)] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> RefreshResponse:
    _validate_csrf(request, csrf_token)
    if refresh_token is None:
        raise Problem(401, "INVALID_REFRESH_TOKEN", "Sessão expirada", "Entre novamente.")
    result, rotated_token = await handle_refresh(refresh_token, repository, settings)
    _set_session_cookies(response, rotated_token, result.csrf_token, settings)
    return result


@router.post("/logout", status_code=204, response_class=Response)
async def sign_out(
    request: Request,
    response: Response,
    repository: Repository,
    settings: Annotated[Settings, Depends(get_settings)],
    refresh_token: Annotated[str | None, Cookie(alias=RefreshCookie)] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Response:
    if refresh_token is not None:
        _validate_csrf(request, csrf_token)
        await handle_sign_out(refresh_token, repository)
    _clear_session_cookies(response, settings)
    response.status_code = 204
    return response


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=201,
    responses={
        200: {"model": RegisterResponse, "description": "Conta pendente ativada"},
        409: {
            "description": "E-mail já cadastrado",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/Problem"},
                },
            },
        },
        422: {
            "description": "Dados de cadastro inválidos",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/Problem"},
                },
            },
        },
        503: {
            "description": "Banco indisponível",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/Problem"},
                },
            },
        },
    },
)
async def sign_up(
    payload: RegisterRequest,
    repository: Repository,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> RegisterResponse:
    async def operation() -> tuple[RegisterResponse, int]:
        return await handle_sign_up(payload, repository)

    return await execute_idempotently(
        key=idempotency_key,
        scope="register",
        request_model=payload,
        response_model=RegisterResponse,
        response=response,
        repository=repository,
        operation=operation,
    )


@router.patch("/me/password", status_code=204, response_class=Response)
async def update_password(
    payload: PasswordChangeRequest,
    user: CurrentUser,
    repository: Repository,
) -> Response:
    await handle_update_password(user, payload, repository)
    return Response(status_code=204)


@router.get("/me", response_model=UserProfile)
async def get_me(user: CurrentUser) -> UserProfile:
    return await handle_get_me(user)


def _cookie_options(settings: Settings) -> tuple[bool, str]:
    secure = settings.environment.lower() in {"production", "prod", "staging"}
    return secure, "none" if secure else "lax"


def _set_session_cookies(
    response: Response,
    token: str,
    csrf_token: str,
    settings: Settings,
) -> None:
    secure, same_site = _cookie_options(settings)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.set_cookie(
        RefreshCookie,
        token,
        max_age=settings.refresh_token_expiry_seconds,
        path=f"{settings.api_prefix}/auth",
        secure=secure,
        httponly=True,
        samesite=same_site,
    )
    response.set_cookie(
        CsrfCookie,
        csrf_token,
        max_age=settings.refresh_token_expiry_seconds,
        path="/",
        secure=secure,
        httponly=False,
        samesite=same_site,
    )


def _clear_session_cookies(response: Response, settings: Settings) -> None:
    secure, same_site = _cookie_options(settings)
    response.delete_cookie(
        RefreshCookie,
        path=f"{settings.api_prefix}/auth",
        secure=secure,
        httponly=True,
        samesite=same_site,
    )
    response.delete_cookie(
        CsrfCookie,
        path="/",
        secure=secure,
        httponly=False,
        samesite=same_site,
    )


def _validate_csrf(request: Request, header_token: str | None) -> None:
    cookie_token = request.cookies.get(CsrfCookie)
    if (
        not cookie_token
        or not header_token
        or not secrets.compare_digest(cookie_token, header_token)
    ):
        raise Problem(
            403,
            "CSRF_VALIDATION_FAILED",
            "Requisição não autorizada",
            "A validação de segurança da sessão falhou.",
        )
