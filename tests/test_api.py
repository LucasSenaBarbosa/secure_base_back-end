import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx

os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-signing-secret-at-least-32-bytes")

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.factory import create_app
from config.settings import Settings
from modules.auth.dependencies import get_current_user, get_repository
from modules.auth.security import hash_password, issue_access_token, verify_password
from modules.repository.supabase_repository import SupabaseRepository
from modules.schemas.auth_schemas import (
    RegisterRequest,
    Role,
    UserProfile,
)
from modules.schemas.users_schemas import AddHomeMemberRequest
from shared.errors.problem_details import Problem

_USER_ID = UUID("a0a0a0a0-a0a0-40a0-80a0-a0a0a0a0a0a0")
_EMAIL = "member@example.com"
_PASSWORD = "correct-password"
_NAME = "Pessoa"

app = create_app()
client = TestClient(app)


def account(
    *,
    user_id: UUID = _USER_ID,
    email: str = _EMAIL,
    password: str | None = _PASSWORD,
    verified: bool = True,
    role: str = "member",
    auth_version: int = 0,
) -> dict[str, object]:
    return {
        "id": str(user_id),
        "email": email,
        "full_name": _NAME,
        "password_hash": hash_password(password) if password else None,
        "role": role,
        "email_verified_at": datetime.now(timezone.utc).isoformat() if verified else None,
        "verification_token_hash": None,
        "verification_expires_at": None,
        "invitation_token_hash": None,
        "invitation_expires_at": None,
        "auth_version": auth_version,
    }


class FakeGateway:
    def __init__(self, ready: bool = True, accounts: list[dict[str, object]] | None = None):
        self.ready = ready
        self.accounts = {
            str(item["email"]).casefold(): item
            for item in ([account()] if accounts is None else accounts)
        }
        self.homes: dict[str, dict[str, object]] = {}
        self.home_members: set[tuple[str, str]] = set()
        self.refresh_sessions: dict[str, dict[str, object]] = {}
        self.idempotency_keys: dict[tuple[str, str], dict[str, object]] = {}

    async def is_ready(self) -> bool:
        return self.ready

    async def create_refresh_session(
        self,
        *,
        user_id: UUID,
        family_id: UUID,
        token_hash: str,
        auth_version: int,
        expires_at: datetime,
    ) -> None:
        self.refresh_sessions[token_hash] = {
            "user_id": user_id,
            "family_id": family_id,
            "auth_version": auth_version,
            "expires_at": expires_at,
            "revoked": False,
        }

    async def rotate_refresh_session(
        self,
        old_token_hash: str,
        new_token_hash: str,
    ) -> dict[str, object] | None:
        session = self.refresh_sessions.get(old_token_hash)
        if (
            session is None
            or session["revoked"]
            or session["expires_at"] <= datetime.now(timezone.utc)
        ):
            return None
        account_row = await self.get_account(session["user_id"])
        if account_row is None or account_row["auth_version"] != session["auth_version"]:
            for saved in self.refresh_sessions.values():
                if saved["family_id"] == session["family_id"]:
                    saved["revoked"] = True
            return None
        session["revoked"] = True
        self.refresh_sessions[new_token_hash] = {**session, "revoked": False}
        return {
            "user_id": session["user_id"],
            "family_id": session["family_id"],
            "auth_version": session["auth_version"],
        }

    async def revoke_refresh_session(self, token_hash: str) -> None:
        session = self.refresh_sessions.get(token_hash)
        if session is not None:
            for saved in self.refresh_sessions.values():
                if saved["family_id"] == session["family_id"]:
                    saved["revoked"] = True

    async def revoke_user_refresh_sessions(self, user_id: UUID) -> None:
        for session in self.refresh_sessions.values():
            if session["user_id"] == user_id:
                session["revoked"] = True

    async def is_refresh_family_active(self, family_id: UUID) -> bool:
        return any(
            session["family_id"] == family_id
            and not session["revoked"]
            and session["expires_at"] > datetime.now(timezone.utc)
            for session in self.refresh_sessions.values()
        )

    async def claim_idempotency(
        self,
        scope: str,
        key_hash: str,
        request_hash: str,
    ) -> dict[str, object]:
        key = (scope, key_hash)
        saved = self.idempotency_keys.get(key)
        if saved and saved["expires_at"] <= datetime.now(timezone.utc):
            del self.idempotency_keys[key]
            saved = None
        if saved is None:
            self.idempotency_keys[key] = {
                "request_hash": request_hash,
                "status_code": None,
                "response_body": None,
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=24),
            }
            return {"state": "new"}
        if saved["request_hash"] != request_hash:
            return {"state": "conflict"}
        if saved["response_body"] is not None:
            return {
                "state": "replay",
                "status_code": saved["status_code"],
                "response_body": saved["response_body"],
            }
        return {"state": "in_progress"}

    async def complete_idempotency(
        self,
        scope: str,
        key_hash: str,
        request_hash: str,
        status_code: int,
        response_body: dict[str, object],
    ) -> None:
        saved = self.idempotency_keys[(scope, key_hash)]
        if saved["request_hash"] != request_hash:
            raise AssertionError("idempotency request hash changed")
        saved["status_code"] = status_code
        saved["response_body"] = response_body

    async def release_idempotency(
        self,
        scope: str,
        key_hash: str,
        request_hash: str,
    ) -> None:
        saved = self.idempotency_keys.get((scope, key_hash))
        if saved and saved["request_hash"] == request_hash:
            del self.idempotency_keys[(scope, key_hash)]

    async def get_account_by_email(self, email: str) -> dict[str, object] | None:
        return self.accounts.get(email.casefold())

    async def get_account(self, user_id: UUID) -> dict[str, object] | None:
        return next(
            (item for item in self.accounts.values() if item["id"] == str(user_id)),
            None,
        )

    async def create_account(
        self,
        *,
        email: str,
        name: str,
        password_hash: str | None,
        verification_token_hash: str | None = None,
        verification_expires_at: datetime | None = None,
        invitation_token_hash: str | None = None,
        invitation_expires_at: datetime | None = None,
    ) -> dict[str, object]:
        if email.casefold() in self.accounts:
            raise Problem(409, "ACCOUNT_CONFLICT", "Conflito", "Conta existente.")
        created = {
            **account(user_id=uuid4(), email=email, password=None, verified=False),
            "full_name": name,
            "password_hash": password_hash,
            "verification_token_hash": verification_token_hash,
            "verification_expires_at": (
                verification_expires_at.isoformat() if verification_expires_at else None
            ),
            "invitation_token_hash": invitation_token_hash,
            "invitation_expires_at": (
                invitation_expires_at.isoformat() if invitation_expires_at else None
            ),
        }
        self.accounts[email.casefold()] = created
        return created

    async def find_account_by_verification_token(
        self,
        token_hash: str,
    ) -> dict[str, object] | None:
        return next(
            (
                item
                for item in self.accounts.values()
                if item["verification_token_hash"] == token_hash
            ),
            None,
        )

    async def find_account_by_invitation_token(
        self,
        token_hash: str,
    ) -> dict[str, object] | None:
        return next(
            (
                item
                for item in self.accounts.values()
                if item["invitation_token_hash"] == token_hash
            ),
            None,
        )

    async def update_account(
        self,
        user_id: UUID,
        payload: dict[str, object],
        *,
        filters: dict[str, str] | None = None,
    ) -> dict[str, object] | None:
        item = await self.get_account(user_id)
        if item is None:
            return None
        for key, condition in (filters or {}).items():
            value = item.get(key)
            if condition == "is.null" and value is not None:
                return None
            if condition.startswith("eq.") and str(value) != condition[3:]:
                return None
            if condition.startswith("gt.") and str(value) <= condition[3:]:
                return None
        item.update(payload)
        return item

    async def get_profile(self, user_id: UUID) -> UserProfile:
        item = await self.get_account(user_id)
        if item is None:
            raise Problem(404, "USER_NOT_FOUND", "Não encontrado", "Conta inexistente.")
        return self.to_profile(item)

    async def list_profiles(self) -> list[UserProfile]:
        return [self.to_profile(item) for item in self.accounts.values()]

    async def delete_user(self, user_id: UUID) -> None:
        item = await self.get_account(user_id)
        if item is None:
            raise Problem(404, "USER_NOT_FOUND", "Não encontrado", "Conta inexistente.")
        del self.accounts[str(item["email"]).casefold()]
        self.home_members = {
            membership
            for membership in self.home_members
            if membership[1] != str(user_id)
        }

    async def create_home(self, name: str, primary_user_id: UUID) -> dict[str, object]:
        home_id = str(uuid4())
        home = {
            "id": home_id,
            "name": name,
            "primary_user_id": str(primary_user_id),
        }
        self.homes[home_id] = home
        return home

    async def get_home(self, home_id: UUID) -> dict[str, object] | None:
        return self.homes.get(str(home_id))

    async def list_homes(
        self,
        user_id: UUID,
        *,
        is_master: bool,
    ) -> list[dict[str, object]]:
        home_ids = {
            home_id
            for home_id, home in self.homes.items()
            if is_master or home["primary_user_id"] == str(user_id)
        }
        home_ids.update(
            home_id for home_id, member_id in self.home_members if member_id == str(user_id)
        )
        return [self.homes[home_id] for home_id in sorted(home_ids)]

    async def list_home_members(self, home_id: UUID) -> list[UserProfile]:
        home = await self.get_home(home_id)
        if home is None:
            raise Problem(404, "HOME_NOT_FOUND", "Não encontrada", "Residência inexistente.")
        ids = {str(home["primary_user_id"])} | {
            user_id
            for member_home_id, user_id in self.home_members
            if member_home_id == str(home_id)
        }
        profiles = []
        for item in self.accounts.values():
            if str(item["id"]) not in ids:
                continue
            profile = self.to_profile(item)
            role = (
                Role.MASTER
                if profile.role == Role.MASTER
                else Role.PRIMARY
                if str(profile.id) == str(home["primary_user_id"])
                else Role.MEMBER
            )
            profiles.append(profile.model_copy(update={"role": role}))
        return profiles

    async def add_home_member(self, home_id: UUID, user_id: UUID) -> None:
        membership = (str(home_id), str(user_id))
        if membership in self.home_members:
            raise Problem(409, "HOME_MEMBER_CONFLICT", "Conflito", "Membro existente.")
        self.home_members.add(membership)

    async def is_home_member(self, home_id: UUID, user_id: UUID) -> bool:
        home = await self.get_home(home_id)
        return bool(
            home is not None
            and (
                home["primary_user_id"] == str(user_id)
                or (str(home_id), str(user_id)) in self.home_members
            )
        )

    async def transfer_home_primary(
        self,
        home_id: UUID,
        new_primary_id: UUID,
    ) -> dict[str, object]:
        home = await self.get_home(home_id)
        if home is None:
            raise Problem(404, "HOME_NOT_FOUND", "Não encontrada", "Residência inexistente.")
        if not await self.is_home_member(home_id, new_primary_id):
            raise Problem(409, "HOME_MEMBER_REQUIRED", "Conflito", "Membro inexistente.")
        old_primary_id = str(home["primary_user_id"])
        self.home_members.add((str(home_id), old_primary_id))
        home["primary_user_id"] = str(new_primary_id)
        return home

    async def remove_home_member(self, home_id: UUID, user_id: UUID) -> None:
        membership = (str(home_id), str(user_id))
        if membership not in self.home_members:
            raise Problem(404, "HOME_MEMBER_NOT_FOUND", "Não encontrado", "Membro inexistente.")
        self.home_members.remove(membership)

    async def user_owns_homes(self, user_id: UUID) -> bool:
        return any(
            home["primary_user_id"] == str(user_id) for home in self.homes.values()
        )

    @staticmethod
    def to_profile(item: dict[str, object]) -> UserProfile:
        return UserProfile(
            id=UUID(str(item["id"])),
            email=str(item["email"]),
            name=str(item["full_name"]),
            role=Role(str(item["role"])),
        )


def settings() -> Settings:
    return Settings(
        supabase_url="http://127.0.0.1:54321",
        supabase_secret_key="test-secret-key",
        jwt_secret_key="test-signing-secret-at-least-32-bytes",
    )


def test_login_returns_api_jwt_and_profile() -> None:
    app.dependency_overrides[get_repository] = lambda: FakeGateway()
    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": _EMAIL, "password": _PASSWORD},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert len(body["access_token"].split(".")) == 3
    assert "refresh_token" not in body
    assert response.cookies.get("securebase-refresh")
    assert response.cookies.get("securebase-csrf")
    assert body["csrf_token"] == response.cookies["securebase-csrf"]
    assert "httponly" in response.headers["set-cookie"].lower()
    assert response.headers["cache-control"] == "no-store"
    assert body["user"]["role"] == "member"


def test_login_does_not_require_email_verification() -> None:
    gateway = FakeGateway(accounts=[account(verified=False)])
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": _EMAIL, "password": _PASSWORD},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


def test_refresh_rotates_cookie_and_requires_csrf() -> None:
    gateway = FakeGateway()
    test_client = TestClient(app)
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        logged_in = test_client.post(
            "/api/v1/auth/login",
            json={"email": _EMAIL, "password": _PASSWORD},
        )
        csrf = logged_in.cookies["securebase-csrf"]
        first_refresh = logged_in.cookies["securebase-refresh"]
        refreshed = test_client.post(
            "/api/v1/auth/refresh",
            headers={"X-CSRF-Token": csrf},
        )
        rejected = test_client.post("/api/v1/auth/refresh")
    finally:
        app.dependency_overrides.clear()

    assert logged_in.status_code == 200
    assert refreshed.status_code == 200
    assert refreshed.cookies["securebase-refresh"] != first_refresh
    assert refreshed.json()["expires_in"] == 900
    assert refreshed.json()["csrf_token"] == refreshed.cookies["securebase-csrf"]
    assert rejected.status_code == 403
    assert rejected.json()["code"] == "CSRF_VALIDATION_FAILED"


def test_logout_revokes_refresh_session_and_clears_cookie() -> None:
    gateway = FakeGateway()
    test_client = TestClient(app)
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        logged_in = test_client.post(
            "/api/v1/auth/login",
            json={"email": _EMAIL, "password": _PASSWORD},
        )
        access_token = logged_in.json()["access_token"]
        refresh_token = logged_in.cookies["securebase-refresh"]
        csrf = logged_in.cookies["securebase-csrf"]
        response = test_client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": csrf},
        )
        protected_response = test_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert all(session["revoked"] for session in gateway.refresh_sessions.values())
    assert "securebase-refresh" in response.headers["set-cookie"]
    assert refresh_token not in response.headers["set-cookie"]
    assert protected_response.status_code == 401


def test_register_saves_hash_without_email_verification() -> None:
    gateway = FakeGateway(accounts=[])
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "new.member@example.com",
                "password": _PASSWORD,
                "name": "Nova Pessoa",
            },
            headers={"Idempotency-Key": "register-test-key-0001"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    created = gateway.accounts["new.member@example.com"]
    assert created["role"] == "member"
    assert created["password_hash"] != _PASSWORD
    assert str(created["password_hash"]).startswith("scrypt$")
    assert created["email_verified_at"] is None


def test_duplicate_registration_returns_conflict_problem() -> None:
    app.dependency_overrides[get_repository] = lambda: FakeGateway()
    try:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": _EMAIL, "password": _PASSWORD, "name": _NAME},
            headers={"Idempotency-Key": "register-test-key-0002"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["x-request-id"] == response.json()["traceId"]
    assert response.json()["code"] == "ACCOUNT_ALREADY_EXISTS"
    assert response.json()["status"] == 409


def test_register_openapi_documents_creation_and_problem_statuses() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    register = response.json()["paths"]["/api/v1/auth/register"]["post"]
    assert {"200", "201", "409", "422", "503"} <= register["responses"].keys()
    assert any(
        parameter["name"] == "Idempotency-Key" and parameter["in"] == "header"
        for parameter in register["parameters"]
    )
    for status_code in ("409", "422", "503"):
        assert "application/problem+json" in register["responses"][status_code]["content"]
    assert "application/problem+json" in register["responses"]["default"]["content"]
    readiness = response.json()["paths"]["/health/ready"]["get"]
    assert (
        readiness["responses"]["503"]["content"]["application/problem+json"]["example"][
            "code"
        ]
        == "DATABASE_UNAVAILABLE"
    )


def test_openapi_documents_problem_responses_for_every_operation() -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    problem_schema = schema["components"]["schemas"]["Problem"]

    assert {"type", "title", "status", "detail", "instance", "code", "traceId"} <= set(
        problem_schema["required"]
    )

    for path_item in paths.values():
        for operation in path_item.values():
            if "responses" not in operation:
                continue
            assert (
                "application/problem+json"
                in operation["responses"]["default"]["content"]
            )
            if "422" in operation["responses"]:
                assert (
                    "application/problem+json"
                    in operation["responses"]["422"]["content"]
                )


def test_auth_contract_uses_patch_for_password_and_home_primary() -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "patch" in paths["/api/v1/auth/me/password"]
    assert "/api/v1/auth/password" not in paths
    assert "patch" in paths["/api/v1/homes/{home_id}/primary"]
    assert "put" not in paths["/api/v1/homes/{home_id}/primary"]
    assert "post" in paths["/api/v1/auth/refresh"]
    assert "post" in paths["/api/v1/auth/logout"]


def test_register_requires_idempotency_key() -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "new.member@example.com",
            "password": _PASSWORD,
            "name": "Nova Pessoa",
        },
    )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["x-request-id"] == response.json()["traceId"]
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_registration_replays_idempotent_response() -> None:
    gateway = FakeGateway(accounts=[])
    test_client = TestClient(app)
    app.dependency_overrides[get_repository] = lambda: gateway
    headers = {"Idempotency-Key": "register-idempotency-key-0001"}
    request = {
        "email": "new.member@example.com",
        "password": _PASSWORD,
        "name": "Nova Pessoa",
    }
    try:
        created = test_client.post(
            "/api/v1/auth/register",
            json=request,
            headers=headers,
        )
        replay = test_client.post(
            "/api/v1/auth/register",
            json=request,
            headers=headers,
        )
        conflict = test_client.post(
            "/api/v1/auth/register",
            json={**request, "name": "Outra Pessoa"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 201
    assert replay.status_code == 201
    assert replay.headers["idempotency-replayed"] == "true"
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert len(gateway.accounts) == 1


def test_registration_requires_strong_password_and_rejects_role() -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "new.member@example.com",
            "password": "short",
            "name": "Nova Pessoa",
            "role": "primary",
        },
    )
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["x-request-id"] == response.json()["traceId"]
    assert {
        "type",
        "title",
        "status",
        "detail",
        "instance",
        "code",
        "fields",
        "traceId",
    } <= response.json().keys()
    assert response.json()["code"] == "VALIDATION_ERROR"

    with pytest.raises(ValidationError):
        RegisterRequest(
            email="new.member@example.com",
            password=_PASSWORD,
            name="Nova Pessoa",
            role="primary",
        )


def test_registration_allows_immediate_login() -> None:
    gateway = FakeGateway(accounts=[])
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        registered = client.post(
            "/api/v1/auth/register",
            json={
                "email": "new.member@example.com",
                "password": _PASSWORD,
                "name": "Nova Pessoa",
            },
            headers={"Idempotency-Key": "register-test-key-0003"},
        )
        logged_in = client.post(
            "/api/v1/auth/login",
            json={"email": "new.member@example.com", "password": _PASSWORD},
        )
    finally:
        app.dependency_overrides.clear()

    assert registered.status_code == 201
    assert logged_in.status_code == 200


def test_registration_claims_legacy_passwordless_account() -> None:
    invited = account(password=None)
    invited["invitation_token_hash"] = "legacy-invitation"
    invited["invitation_expires_at"] = "2026-10-25T20:00:00+00:00"
    gateway = FakeGateway(accounts=[invited])
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": _EMAIL, "password": _PASSWORD, "name": _NAME},
            headers={"Idempotency-Key": "register-test-key-0004"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert verify_password(_PASSWORD, invited["password_hash"])
    assert invited["invitation_token_hash"] is None
    assert invited["invitation_expires_at"] is None


def test_registration_returns_conflict_when_legacy_account_is_claimed_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invited = account(password=None)
    gateway = FakeGateway(accounts=[invited])

    async def concurrent_claim(*_args, **_kwargs):
        return None

    monkeypatch.setattr(gateway, "update_account", concurrent_claim)
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": _EMAIL, "password": _PASSWORD, "name": _NAME},
            headers={"Idempotency-Key": "register-test-key-0005"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["code"] == "ACCOUNT_ALREADY_EXISTS"


def test_authenticated_profile_accepts_custom_jwt() -> None:
    gateway = FakeGateway()
    session_id = UUID("f0f0f0f0-f0f0-40f0-80f0-f0f0f0f0f0f0")
    gateway.refresh_sessions["active-test-token"] = {
        "user_id": _USER_ID,
        "family_id": session_id,
        "auth_version": 0,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        "revoked": False,
    }
    token, _ = issue_access_token(settings(), _USER_ID, 0, session_id)
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["id"] == str(_USER_ID)


def test_authenticated_profile_rejects_modified_token() -> None:
    app.dependency_overrides[get_repository] = lambda: FakeGateway()
    try:
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer a.b.c"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_ACCESS_TOKEN"


def test_password_hash_verification() -> None:
    encoded = hash_password(_PASSWORD)

    assert encoded != _PASSWORD
    assert verify_password(_PASSWORD, encoded)
    assert not verify_password("wrong-password", encoded)
    assert not verify_password(_PASSWORD, None)


def test_supabase_repository_only_calls_postgrest_for_account_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = SupabaseRepository(settings())

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/v1/securebase_users"
        assert request.url.params["email"] == "eq.member@example.com"
        assert request.headers["apikey"] == "test-secret-key"
        assert "authorization" in request.headers
        return httpx.Response(200, json=[])

    monkeypatch.setattr(
        gateway,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )

    import asyncio

    assert asyncio.run(gateway.get_account_by_email(_EMAIL)) is None


def test_live_health_is_public() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


def test_ready_health_checks_database() -> None:
    app.dependency_overrides[get_repository] = lambda: FakeGateway()
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


def test_ready_health_returns_database_problem_when_database_is_unavailable() -> None:
    app.dependency_overrides[get_repository] = lambda: FakeGateway(ready=False)
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["x-request-id"] == response.json()["traceId"]
    assert response.json()["code"] == "DATABASE_UNAVAILABLE"


@pytest.mark.parametrize(
    ("method", "path", "status_code", "error_code"),
    [
        ("GET", "/api/v1/route-that-does-not-exist", 404, "NOT_FOUND"),
        ("PUT", "/health/live", 405, "METHOD_NOT_ALLOWED"),
    ],
)
def test_framework_http_errors_use_problem_details(
    method: str,
    path: str,
    status_code: int,
    error_code: str,
) -> None:
    response = client.request(method, path)

    assert response.status_code == status_code
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["x-request-id"] == response.json()["traceId"]
    assert response.json()["code"] == error_code


def test_protected_profile_requires_bearer_token() -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


def test_member_cannot_list_users() -> None:
    member = UserProfile(
        id=_USER_ID,
        email=_EMAIL,
        name=_NAME,
        role=Role.MEMBER,
    )
    app.dependency_overrides[get_current_user] = lambda: member
    try:
        response = client.get("/api/v1/users")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_primary_cannot_list_global_users() -> None:
    primary = UserProfile(
        id=UUID("b0b0b0b0-b0b0-40b0-80b0-b0b0b0b0b0b0"),
        email="admin@example.com",
        name="Admin",
        role=Role.PRIMARY,
    )
    app.dependency_overrides[get_current_user] = lambda: primary
    app.dependency_overrides[get_repository] = lambda: FakeGateway()
    try:
        response = client.get("/api/v1/users")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_master_can_list_profiles() -> None:
    master = UserProfile(
        id=UUID("b0b0b0b0-b0b0-40b0-80b0-b0b0b0b0b0b0"),
        email="master@example.com",
        name="Master",
        role=Role.MASTER,
    )
    app.dependency_overrides[get_current_user] = lambda: master
    app.dependency_overrides[get_repository] = lambda: FakeGateway()
    try:
        response = client.get("/api/v1/users")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


def test_master_can_remove_primary_account() -> None:
    master = UserProfile(
        id=UUID("b0b0b0b0-b0b0-40b0-80b0-b0b0b0b0b0b0"),
        email="master@example.com",
        name="Master",
        role=Role.MASTER,
    )
    primary_id = UUID("c0c0c0c0-c0c0-40c0-80c0-c0c0c0c0c0c0")
    gateway = FakeGateway(
        accounts=[
            account(user_id=master.id, email="master@example.com", role="master"),
            account(user_id=primary_id, email="primary@example.com", role="primary"),
        ]
    )
    app.dependency_overrides[get_current_user] = lambda: master
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.delete(f"/api/v1/users/{primary_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert "primary@example.com" not in gateway.accounts


def test_master_cannot_remove_another_master() -> None:
    master_id = UUID("b0b0b0b0-b0b0-40b0-80b0-b0b0b0b0b0b0")
    target_id = UUID("c0c0c0c0-c0c0-40c0-80c0-c0c0c0c0c0c0")
    master = UserProfile(
        id=master_id,
        email="master@example.com",
        name="Master",
        role=Role.MASTER,
    )
    gateway = FakeGateway(
        accounts=[
            account(user_id=master_id, email="master@example.com", role="master"),
            account(user_id=target_id, email="other-master@example.com", role="master"),
        ]
    )
    app.dependency_overrides[get_current_user] = lambda: master
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.delete(f"/api/v1/users/{target_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "other-master@example.com" in gateway.accounts


def test_primary_cannot_delete_global_user() -> None:
    actor_id = UUID("b0b0b0b0-b0b0-40b0-80b0-b0b0b0b0b0b0")
    target_id = UUID("c0c0c0c0-c0c0-40c0-80c0-c0c0c0c0c0c0")
    primary = UserProfile(
        id=actor_id,
        email="primary@example.com",
        name="Primary",
        role=Role.PRIMARY,
    )
    gateway = FakeGateway(
        accounts=[
            account(user_id=actor_id, email="primary@example.com", role="primary"),
            account(user_id=target_id, email="other-primary@example.com", role="primary"),
        ]
    )
    app.dependency_overrides[get_current_user] = lambda: primary
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.delete(f"/api/v1/users/{target_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_house_primary_can_manage_only_owned_home() -> None:
    owner_id = UUID("b0b0b0b0-b0b0-40b0-80b0-b0b0b0b0b0b0")
    own_home_id = UUID("d0d0d0d0-d0d0-40d0-80d0-d0d0d0d0d0d0")
    other_home_id = UUID("e0e0e0e0-e0e0-40e0-80e0-e0e0e0e0e0e0")
    owner = UserProfile(
        id=owner_id,
        email="owner@example.com",
        name="Owner",
        role=Role.MEMBER,
    )
    gateway = FakeGateway(accounts=[account(user_id=owner_id, email="owner@example.com")])
    gateway.homes[str(own_home_id)] = {
        "id": str(own_home_id),
        "name": "Minha casa",
        "primary_user_id": str(owner_id),
    }
    gateway.homes[str(other_home_id)] = {
        "id": str(other_home_id),
        "name": "Outra casa",
        "primary_user_id": str(_USER_ID),
    }
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        own_response = client.get(f"/api/v1/homes/{own_home_id}/users")
        other_response = client.get(f"/api/v1/homes/{other_home_id}/users")
    finally:
        app.dependency_overrides.clear()

    assert own_response.status_code == 200
    assert own_response.json()[0]["role"] == "primary"
    assert other_response.status_code == 403


def test_master_can_manage_any_home() -> None:
    master = UserProfile(
        id=UUID("b0b0b0b0-b0b0-40b0-80b0-b0b0b0b0b0b0"),
        email="master@example.com",
        name="Master",
        role=Role.MASTER,
    )
    home_id = UUID("d0d0d0d0-d0d0-40d0-80d0-d0d0d0d0d0d0")
    gateway = FakeGateway(accounts=[account()])
    gateway.homes[str(home_id)] = {
        "id": str(home_id),
        "name": "Casa da comunidade",
        "primary_user_id": str(_USER_ID),
    }
    app.dependency_overrides[get_current_user] = lambda: master
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.get(f"/api/v1/homes/{home_id}/users")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


def test_master_can_transfer_home_primary_to_existing_member() -> None:
    master_id = UUID("b0b0b0b0-b0b0-40b0-80b0-b0b0b0b0b0b0")
    old_primary_id = UUID("c0c0c0c0-c0c0-40c0-80c0-c0c0c0c0c0c0")
    new_primary_id = UUID("f0f0f0f0-f0f0-40f0-80f0-f0f0f0f0f0f0")
    home_id = UUID("d0d0d0d0-d0d0-40d0-80d0-d0d0d0d0d0d0")
    master = UserProfile(
        id=master_id,
        email="master@example.com",
        name="Master",
        role=Role.MASTER,
    )
    gateway = FakeGateway(
        accounts=[
            account(user_id=master_id, email="master@example.com", role="master"),
            account(user_id=old_primary_id, email="old-primary@example.com", role="primary"),
            account(user_id=new_primary_id, email="new-primary@example.com"),
        ]
    )
    gateway.homes[str(home_id)] = {
        "id": str(home_id),
        "name": "Minha casa",
        "primary_user_id": str(old_primary_id),
    }
    gateway.home_members.add((str(home_id), str(new_primary_id)))
    app.dependency_overrides[get_current_user] = lambda: master
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.patch(
            f"/api/v1/homes/{home_id}/primary",
            json={"user_id": str(new_primary_id)},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["primary_user_id"] == str(new_primary_id)
    assert (str(home_id), str(old_primary_id)) in gateway.home_members


def test_user_can_belong_to_multiple_homes() -> None:
    member_id = UUID("f0f0f0f0-f0f0-40f0-80f0-f0f0f0f0f0f0")
    member = UserProfile(
        id=member_id,
        email="member@example.com",
        name="Member",
        role=Role.MEMBER,
    )
    gateway = FakeGateway(
        accounts=[
            account(user_id=member_id, email="member@example.com"),
            account(user_id=_USER_ID, email="owner@example.com"),
            account(
                user_id=UUID("e0e0e0e0-e0e0-40e0-80e0-e0e0e0e0e0e0"),
                email="other-owner@example.com",
            ),
        ]
    )
    home_ids = [
        UUID("d0d0d0d0-d0d0-40d0-80d0-d0d0d0d0d0d0"),
        UUID("c0c0c0c0-c0c0-40c0-80c0-c0c0c0c0c0c0"),
    ]
    gateway.homes[str(home_ids[0])] = {
        "id": str(home_ids[0]),
        "name": "Casa A",
        "primary_user_id": str(_USER_ID),
    }
    gateway.homes[str(home_ids[1])] = {
        "id": str(home_ids[1]),
        "name": "Casa B",
        "primary_user_id": "e0e0e0e0-e0e0-40e0-80e0-e0e0e0e0e0e0",
    }
    gateway.home_members.update((str(home_id), str(member_id)) for home_id in home_ids)
    app.dependency_overrides[get_current_user] = lambda: member
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.get("/api/v1/homes")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert {home["id"] for home in response.json()} == {str(home_id) for home_id in home_ids}
    assert {home["role"] for home in response.json()} == {"member"}


def test_authenticated_user_can_create_home_as_primary() -> None:
    owner = UserProfile(
        id=_USER_ID,
        email=_EMAIL,
        name=_NAME,
        role=Role.MEMBER,
    )
    gateway = FakeGateway()
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.post(
            "/api/v1/homes",
            json={"name": " Minha casa "},
            headers={"Idempotency-Key": "home-create-test-key-0001"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["name"] == "Minha casa"
    assert response.json()["primary_user_id"] == str(_USER_ID)
    assert response.json()["role"] == "primary"


def test_home_creation_replays_existing_result_for_same_key() -> None:
    owner = UserProfile(id=_USER_ID, email=_EMAIL, name=_NAME, role=Role.MEMBER)
    gateway = FakeGateway()
    test_client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_repository] = lambda: gateway
    headers = {"Idempotency-Key": "home-idempotency-key-0001"}
    try:
        first = test_client.post(
            "/api/v1/homes",
            json={"name": "Minha casa"},
            headers=headers,
        )
        replay = test_client.post(
            "/api/v1/homes",
            json={"name": "Minha casa"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.headers["idempotency-replayed"] == "true"
    assert len(gateway.homes) == 1


def test_password_change_invalidates_access_and_refresh_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = FakeGateway()
    test_client = TestClient(app)

    async def skip_refresh_revocation(_user_id: UUID) -> None:
        return None

    monkeypatch.setattr(gateway, "revoke_user_refresh_sessions", skip_refresh_revocation)
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        login_response = test_client.post(
            "/api/v1/auth/login",
            json={"email": _EMAIL, "password": _PASSWORD},
        )
        token = login_response.json()["access_token"]
        csrf = login_response.cookies["securebase-csrf"]
        changed = test_client.patch(
            "/api/v1/auth/me/password",
            json={
                "current_password": _PASSWORD,
                "new_password": "new-strong-password",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        old_refresh = test_client.post(
            "/api/v1/auth/refresh",
            headers={"X-CSRF-Token": csrf},
        )
        old_token_request = test_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert changed.status_code == 204
    assert old_refresh.status_code == 401
    assert old_token_request.status_code == 401


def test_primary_adds_existing_user_only_to_selected_home() -> None:
    owner_id = UUID("b0b0b0b0-b0b0-40b0-80b0-b0b0b0b0b0b0")
    user_id = UUID("f0f0f0f0-f0f0-40f0-80f0-f0f0f0f0f0f0")
    home_id = UUID("d0d0d0d0-d0d0-40d0-80d0-d0d0d0d0d0d0")
    owner = UserProfile(
        id=owner_id,
        email="owner@example.com",
        name="Owner",
        role=Role.MEMBER,
    )
    gateway = FakeGateway(
        accounts=[
            account(user_id=owner_id, email="owner@example.com"),
            account(user_id=user_id, email="member@example.com"),
        ]
    )
    gateway.homes[str(home_id)] = {
        "id": str(home_id),
        "name": "Minha casa",
        "primary_user_id": str(owner_id),
    }
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.post(
            f"/api/v1/homes/{home_id}/users",
            json={"email": "member@example.com"},
            headers={"Idempotency-Key": "home-member-test-key-0001"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["role"] == "member"
    assert (str(home_id), str(user_id)) in gateway.home_members


def test_primary_cannot_add_unregistered_user_to_home() -> None:
    owner_id = UUID("b0b0b0b0-b0b0-40b0-80b0-b0b0b0b0b0b0")
    home_id = UUID("d0d0d0d0-d0d0-40d0-80d0-d0d0d0d0d0d0")
    owner = UserProfile(
        id=owner_id,
        email="owner@example.com",
        name="Owner",
        role=Role.MEMBER,
    )
    gateway = FakeGateway(accounts=[account(user_id=owner_id, email="owner@example.com")])
    gateway.homes[str(home_id)] = {
        "id": str(home_id),
        "name": "Minha casa",
        "primary_user_id": str(owner_id),
    }
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.post(
            f"/api/v1/homes/{home_id}/users",
            json={"email": "new.member@example.com"},
            headers={"Idempotency-Key": "home-member-test-key-0002"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


def test_removing_house_member_preserves_account_and_other_house_access() -> None:
    owner_id = UUID("b0b0b0b0-b0b0-40b0-80b0-b0b0b0b0b0b0")
    user_id = UUID("f0f0f0f0-f0f0-40f0-80f0-f0f0f0f0f0f0")
    home_ids = [
        UUID("d0d0d0d0-d0d0-40d0-80d0-d0d0d0d0d0d0"),
        UUID("c0c0c0c0-c0c0-40c0-80c0-c0c0c0c0c0c0"),
    ]
    owner = UserProfile(
        id=owner_id,
        email="owner@example.com",
        name="Owner",
        role=Role.MEMBER,
    )
    gateway = FakeGateway(
        accounts=[
            account(user_id=owner_id, email="owner@example.com"),
            account(user_id=user_id, email="member@example.com"),
        ]
    )
    for home_id in home_ids:
        gateway.homes[str(home_id)] = {
            "id": str(home_id),
            "name": "Minha casa",
            "primary_user_id": str(owner_id),
        }
        gateway.home_members.add((str(home_id), str(user_id)))
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_repository] = lambda: gateway
    try:
        response = client.delete(f"/api/v1/homes/{home_ids[0]}/users/{user_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert "member@example.com" in gateway.accounts
    assert (str(home_ids[0]), str(user_id)) not in gateway.home_members
    assert (str(home_ids[1]), str(user_id)) in gateway.home_members


def test_user_creation_rejects_client_supplied_role() -> None:
    with pytest.raises(ValidationError):
        AddHomeMemberRequest(
            email="member@example.com",
            role="primary",
        )


def test_hosted_settings_require_tls() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            supabase_url="http://127.0.0.1:54321",
            supabase_secret_key="test-secret-key",
            jwt_secret_key="test-signing-secret-at-least-32-bytes",
            cors_origins=["https://app.example.com"],
        )
