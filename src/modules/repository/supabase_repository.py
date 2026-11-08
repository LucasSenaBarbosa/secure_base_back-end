from datetime import datetime, timezone
from typing import Any, TypedDict
from uuid import UUID

import httpx

from config.settings import Settings
from modules.schemas.auth_schemas import Role, UserProfile
from shared.errors.problem_details import Problem

_ACCOUNT_FIELDS = (
    "id,email,full_name,role,password_hash,auth_version"
)


_RUN_SUMMARY_FIELDS = (
    "id,home_id,created_at,created_by,layout_version,library,population_size,"
    "generations,seed,evaluations,duration_ms,status,solution_count"
)
_SOLUTION_FIELDS = "id,run_id,solution_index,sensors,coverage,cost,vulnerability,sensors_by_type"
_MANUAL_FIELDS = "id,home_id,name,sensors,created_by,created_at"
_LINK_SIMULATION_SUMMARY_FIELDS = (
    "id,home_id,created_at,scenario,intensity,defenses,trials,seed,model_version,"
    "verdict,delivery_rate"
)
_LINK_SIMULATION_DETAIL_FIELDS = f"{_LINK_SIMULATION_SUMMARY_FIELDS},result"
_LAYOUT_FIELDS = "home_id,layout,version,updated_at"


class RotatedRefreshSession(TypedDict):
    user_id: UUID
    family_id: UUID
    auth_version: int


class SupabaseRepository:
    """Accesses SecureBase account data through Supabase PostgREST only."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._base_url = str(settings.supabase_url).rstrip("/")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._settings.supabase_timeout_seconds)

    def _admin_headers(self) -> dict[str, str]:
        secret = self._settings.supabase_secret_key.get_secret_value()
        return {"apikey": secret, "Authorization": f"Bearer {secret}"}

    async def get_account_by_email(self, email: str) -> dict[str, Any] | None:
        rows = await self._request(
            "GET",
            params={
                "email": f"eq.{email}",
                "select": _ACCOUNT_FIELDS,
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    async def get_account(self, user_id: UUID) -> dict[str, Any] | None:
        rows = await self._request(
            "GET",
            params={
                "id": f"eq.{user_id}",
                "select": _ACCOUNT_FIELDS,
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    async def create_account(
        self,
        *,
        email: str,
        name: str,
        password_hash: str,
    ) -> dict[str, Any]:
        payload = {
            "email": email,
            "full_name": name,
            "password_hash": password_hash,
            "role": Role.MEMBER.value,
        }
        result = await self._request(
            "POST",
            payload=payload,
            prefer="return=representation",
            conflict_is_account=True,
        )
        if not result:
            raise Problem(
                503,
                "INVALID_DATABASE_RESPONSE",
                "Serviço temporariamente indisponível",
                "O banco não confirmou a criação da conta.",
            )
        return result[0]

    async def update_account(
        self,
        user_id: UUID,
        payload: dict[str, Any],
        *,
        filters: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        params = {"id": f"eq.{user_id}", **(filters or {})}
        result = await self._request(
            "PATCH",
            params=params,
            payload=payload,
            prefer="return=representation",
        )
        return result[0] if result else None

    async def create_refresh_session(
        self,
        *,
        user_id: UUID,
        family_id: UUID,
        token_hash: str,
        auth_version: int,
        expires_at: datetime,
    ) -> None:
        await self._rpc(
            "securebase_create_refresh_session",
            {
                "p_user_id": str(user_id),
                "p_family_id": str(family_id),
                "p_token_hash": token_hash,
                "p_auth_version": auth_version,
                "p_expires_at": expires_at.isoformat(),
            },
        )

    async def rotate_refresh_session(
        self,
        old_token_hash: str,
        new_token_hash: str,
    ) -> RotatedRefreshSession | None:
        rows = await self._rpc(
            "securebase_rotate_refresh_session",
            {
                "p_token_hash": old_token_hash,
                "p_new_token_hash": new_token_hash,
            },
        )
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise Problem(
                503,
                "INVALID_DATABASE_RESPONSE",
                "Serviço temporariamente indisponível",
                "O banco retornou uma resposta inválida.",
            )
        if rows[0].get("state") != "rotated":
            return None
        try:
            return {
                "user_id": UUID(rows[0]["user_id"]),
                "family_id": UUID(rows[0]["family_id"]),
                "auth_version": int(rows[0]["auth_version"]),
            }
        except (KeyError, ValueError, TypeError) as exc:
            raise Problem(
                503,
                "INVALID_DATABASE_RESPONSE",
                "Serviço temporariamente indisponível",
                "O banco retornou uma resposta inválida.",
            ) from exc

    async def revoke_refresh_session(self, token_hash: str) -> None:
        await self._rpc(
            "securebase_revoke_refresh_session",
            {"p_token_hash": token_hash},
        )

    async def revoke_user_refresh_sessions(self, user_id: UUID) -> None:
        await self._rpc(
            "securebase_revoke_user_refresh_sessions",
            {"p_user_id": str(user_id)},
        )

    async def is_refresh_family_active(self, family_id: UUID) -> bool:
        rows = await self._request(
            "GET",
            table="securebase_refresh_sessions",
            params={
                "family_id": f"eq.{family_id}",
                "revoked_at": "is.null",
                "expires_at": f"gt.{datetime.now(timezone.utc).isoformat()}",
                "select": "id",
                "limit": "1",
            },
        )
        return bool(rows)

    async def claim_idempotency(
        self,
        scope: str,
        key_hash: str,
        request_hash: str,
    ) -> dict[str, Any]:
        rows = await self._rpc(
            "securebase_claim_idempotency_key",
            {
                "p_scope": scope,
                "p_key_hash": key_hash,
                "p_request_hash": request_hash,
            },
        )
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise Problem(
                503,
                "INVALID_DATABASE_RESPONSE",
                "Serviço temporariamente indisponível",
                "O banco não confirmou a chave de idempotência.",
            )
        return rows[0]

    async def complete_idempotency(
        self,
        scope: str,
        key_hash: str,
        request_hash: str,
        status_code: int,
        response_body: dict[str, Any],
    ) -> None:
        await self._rpc(
            "securebase_complete_idempotency_key",
            {
                "p_scope": scope,
                "p_key_hash": key_hash,
                "p_request_hash": request_hash,
                "p_status_code": status_code,
                "p_response_body": response_body,
            },
        )

    async def release_idempotency(
        self,
        scope: str,
        key_hash: str,
        request_hash: str,
    ) -> None:
        await self._rpc(
            "securebase_release_idempotency_key",
            {
                "p_scope": scope,
                "p_key_hash": key_hash,
                "p_request_hash": request_hash,
            },
        )

    async def list_profiles(self) -> list[UserProfile]:
        profiles: list[UserProfile] = []
        offset = 0
        while True:
            rows = await self._request(
                "GET",
                params={
                    "select": "id,email,full_name,role",
                    "order": "email.asc",
                    "limit": "200",
                    "offset": str(offset),
                },
            )
            profiles.extend(self.to_profile(row) for row in rows)
            if len(rows) < 200:
                return profiles
            offset += len(rows)

    async def get_profile(self, user_id: UUID) -> UserProfile:
        account = await self.get_account(user_id)
        if account is None:
            raise Problem(404, "USER_NOT_FOUND", "Não encontrado", "A conta solicitada não existe.")
        return self.to_profile(account)

    async def delete_user(self, user_id: UUID) -> None:
        rows = await self._request(
            "DELETE",
            params={"id": f"eq.{user_id}"},
            prefer="return=representation",
        )
        if not rows:
            raise Problem(404, "USER_NOT_FOUND", "Não encontrado", "A conta solicitada não existe.")

    async def create_home(self, name: str, primary_user_id: UUID) -> dict[str, Any]:
        rows = await self._request(
            "POST",
            table="securebase_homes",
            payload={"name": name, "primary_user_id": str(primary_user_id)},
            prefer="return=representation",
        )
        if not rows:
            raise Problem(
                503,
                "INVALID_DATABASE_RESPONSE",
                "Serviço temporariamente indisponível",
                "O banco não confirmou a criação da residência.",
            )
        return rows[0]

    async def get_home(self, home_id: UUID) -> dict[str, Any] | None:
        rows = await self._request(
            "GET",
            table="securebase_homes",
            params={
                "id": f"eq.{home_id}",
                "select": "id,name,primary_user_id",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    async def list_homes(
        self,
        user_id: UUID,
        *,
        is_master: bool,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"select": "id,name,primary_user_id", "order": "name.asc"}
        if not is_master:
            owned_rows = await self._request(
                "GET",
                table="securebase_homes",
                params={"primary_user_id": f"eq.{user_id}", "select": "id"},
            )
            member_rows = await self._request(
                "GET",
                table="securebase_home_members",
                params={"user_id": f"eq.{user_id}", "select": "home_id"},
            )
            home_ids = {
                str(row["id"]) for row in owned_rows
            } | {
                str(row["home_id"]) for row in member_rows
            }
            if not home_ids:
                return []
            params["id"] = f"in.({','.join(sorted(home_ids))})"
        return await self._request("GET", table="securebase_homes", params=params)

    async def list_home_members(self, home_id: UUID) -> list[UserProfile]:
        home = await self.get_home(home_id)
        if home is None:
            raise Problem(404, "HOME_NOT_FOUND", "Não encontrada", "A residência não existe.")
        member_rows = await self._request(
            "GET",
            table="securebase_home_members",
            params={"home_id": f"eq.{home_id}", "select": "user_id"},
        )
        user_ids = {str(home["primary_user_id"])} | {
            str(row["user_id"]) for row in member_rows
        }
        accounts = await self._request(
            "GET",
            params={
                "id": f"in.({','.join(sorted(user_ids))})",
                "select": "id,email,full_name,role",
                "order": "email.asc",
            },
        )
        profiles = []
        for account in accounts:
            profile = self.to_profile(account)
            if profile.role == Role.MASTER:
                profiles.append(profile)
            elif profile.id == UUID(str(home["primary_user_id"])):
                profiles.append(profile.model_copy(update={"role": Role.PRIMARY}))
            else:
                profiles.append(profile.model_copy(update={"role": Role.MEMBER}))
        return profiles

    async def add_home_member(self, home_id: UUID, user_id: UUID) -> None:
        await self._request(
            "POST",
            table="securebase_home_members",
            payload={"home_id": str(home_id), "user_id": str(user_id)},
            prefer="return=representation",
            conflict_is_membership=True,
        )

    async def is_home_member(self, home_id: UUID, user_id: UUID) -> bool:
        home = await self.get_home(home_id)
        if home is None:
            return False
        if str(home["primary_user_id"]) == str(user_id):
            return True
        rows = await self._request(
            "GET",
            table="securebase_home_members",
            params={
                "home_id": f"eq.{home_id}",
                "user_id": f"eq.{user_id}",
                "select": "user_id",
                "limit": "1",
            },
        )
        return bool(rows)

    async def transfer_home_primary(
        self,
        home_id: UUID,
        new_primary_id: UUID,
    ) -> dict[str, Any]:
        home = await self.get_home(home_id)
        if home is None:
            raise Problem(404, "HOME_NOT_FOUND", "Não encontrada", "A residência não existe.")
        previous_primary_id = UUID(str(home["primary_user_id"]))
        if previous_primary_id == new_primary_id:
            return home
        if not await self.is_home_member(home_id, new_primary_id):
            raise Problem(
                409,
                "HOME_MEMBER_REQUIRED",
                "Conflito",
                "O novo primary precisa pertencer à residência.",
            )
        if not await self.is_home_member(home_id, previous_primary_id):
            await self.add_home_member(home_id, previous_primary_id)
        rows = await self._request(
            "PATCH",
            table="securebase_homes",
            params={
                "id": f"eq.{home_id}",
                "primary_user_id": f"eq.{previous_primary_id}",
                "select": "id,name,primary_user_id",
            },
            payload={"primary_user_id": str(new_primary_id)},
            prefer="return=representation",
        )
        if not rows:
            raise Problem(
                409,
                "HOME_PRIMARY_CONFLICT",
                "Conflito",
                "A residência foi atualizada por outra operação. Atualize os dados e tente "
                "novamente.",
            )
        return rows[0]

    async def remove_home_member(self, home_id: UUID, user_id: UUID) -> None:
        rows = await self._request(
            "DELETE",
            table="securebase_home_members",
            params={"home_id": f"eq.{home_id}", "user_id": f"eq.{user_id}"},
            prefer="return=representation",
        )
        if not rows:
            raise Problem(
                404,
                "HOME_MEMBER_NOT_FOUND",
                "Não encontrado",
                "Este usuário não pertence à residência.",
            )

    async def user_owns_homes(self, user_id: UUID) -> bool:
        rows = await self._request(
            "GET",
            table="securebase_homes",
            params={
                "primary_user_id": f"eq.{user_id}",
                "select": "id",
                "limit": "1",
            },
        )
        return bool(rows)

    async def get_home_layout(self, home_id: UUID) -> dict[str, Any] | None:
        rows = await self._request(
            "GET",
            table="securebase_home_layouts",
            params={"home_id": f"eq.{home_id}", "select": _LAYOUT_FIELDS, "limit": "1"},
        )
        return rows[0] if rows else None

    async def create_home_layout(
        self,
        home_id: UUID,
        layout: dict[str, Any],
        actor_id: UUID,
    ) -> dict[str, Any]:
        rows = await self._request(
            "POST",
            table="securebase_home_layouts",
            params={"select": _LAYOUT_FIELDS},
            payload={"home_id": str(home_id), "layout": layout, "updated_by": str(actor_id)},
            prefer="return=representation",
            conflict=_layout_conflict(),
        )
        if not rows:
            raise _unconfirmed("o layout")
        return rows[0]

    async def update_home_layout(
        self,
        home_id: UUID,
        layout: dict[str, Any],
        expected_version: int,
        actor_id: UUID,
    ) -> dict[str, Any] | None:
        rows = await self._request(
            "PATCH",
            table="securebase_home_layouts",
            params={
                "home_id": f"eq.{home_id}",
                "version": f"eq.{expected_version}",
                "select": _LAYOUT_FIELDS,
            },
            payload={
                "layout": layout,
                "version": expected_version + 1,
                "updated_by": str(actor_id),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            prefer="return=representation",
        )
        return rows[0] if rows else None

    async def create_optimization_run(
        self,
        run: dict[str, Any],
        solutions: list[dict[str, Any]],
    ) -> None:
        await self._rpc(
            "securebase_create_optimization_run",
            {"p_run": run, "p_solutions": solutions},
        )

    async def list_optimization_runs(
        self,
        home_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            table="securebase_optimization_runs",
            params={
                "home_id": f"eq.{home_id}",
                "select": _RUN_SUMMARY_FIELDS,
                "order": "created_at.desc",
                "limit": str(limit),
                "offset": str(offset),
            },
        )

    async def get_optimization_run(
        self,
        home_id: UUID,
        run_id: UUID,
    ) -> dict[str, Any] | None:
        rows = await self._request(
            "GET",
            table="securebase_optimization_runs",
            params={
                "id": f"eq.{run_id}",
                "home_id": f"eq.{home_id}",
                "select": f"{_RUN_SUMMARY_FIELDS},layout_snapshot",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    async def list_optimization_solutions(self, run_id: UUID) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            table="securebase_optimization_solutions",
            params={
                "run_id": f"eq.{run_id}",
                "select": _SOLUTION_FIELDS,
                "order": "solution_index.asc",
            },
        )

    async def get_optimization_solution(
        self,
        run_id: UUID,
        solution_id: UUID,
    ) -> dict[str, Any] | None:
        rows = await self._request(
            "GET",
            table="securebase_optimization_solutions",
            params={
                "id": f"eq.{solution_id}",
                "run_id": f"eq.{run_id}",
                "select": _SOLUTION_FIELDS,
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    async def create_manual_configuration(
        self,
        home_id: UUID,
        name: str,
        sensors: list[dict[str, Any]],
        actor_id: UUID,
    ) -> dict[str, Any]:
        rows = await self._request(
            "POST",
            table="securebase_manual_configurations",
            params={"select": _MANUAL_FIELDS},
            payload={
                "home_id": str(home_id),
                "name": name,
                "sensors": sensors,
                "created_by": str(actor_id),
            },
            prefer="return=representation",
        )
        if not rows:
            raise _unconfirmed("a configuração manual")
        return rows[0]

    async def list_manual_configurations(self, home_id: UUID) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            table="securebase_manual_configurations",
            params={
                "home_id": f"eq.{home_id}",
                "select": _MANUAL_FIELDS,
                "order": "created_at.desc",
                "limit": "100",
            },
        )

    async def get_manual_configuration(
        self,
        home_id: UUID,
        configuration_id: UUID,
    ) -> dict[str, Any] | None:
        rows = await self._request(
            "GET",
            table="securebase_manual_configurations",
            params={
                "id": f"eq.{configuration_id}",
                "home_id": f"eq.{home_id}",
                "select": _MANUAL_FIELDS,
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    async def delete_manual_configuration(
        self,
        home_id: UUID,
        configuration_id: UUID,
    ) -> bool:
        rows = await self._request(
            "DELETE",
            table="securebase_manual_configurations",
            params={"id": f"eq.{configuration_id}", "home_id": f"eq.{home_id}"},
            prefer="return=representation",
        )
        return bool(rows)

    async def create_link_simulation(self, simulation: dict[str, Any]) -> dict[str, Any]:
        rows = await self._request(
            "POST",
            table="securebase_link_simulations",
            params={"select": _LINK_SIMULATION_DETAIL_FIELDS},
            payload=simulation,
            prefer="return=representation",
        )
        if not rows:
            raise _unconfirmed("a simulação de rede")
        return rows[0]

    async def list_link_simulations(
        self,
        home_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            table="securebase_link_simulations",
            params={
                "home_id": f"eq.{home_id}",
                "select": _LINK_SIMULATION_SUMMARY_FIELDS,
                "order": "created_at.desc",
                "limit": str(limit),
                "offset": str(offset),
            },
        )

    async def get_link_simulation(
        self,
        home_id: UUID,
        simulation_id: UUID,
    ) -> dict[str, Any] | None:
        rows = await self._request(
            "GET",
            table="securebase_link_simulations",
            params={
                "id": f"eq.{simulation_id}",
                "home_id": f"eq.{home_id}",
                "select": _LINK_SIMULATION_DETAIL_FIELDS,
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    async def is_ready(self) -> bool:
        try:
            async with self._client() as client:
                for table, column in (
                    ("securebase_users", "id"),
                    ("securebase_homes", "id"),
                    ("securebase_home_members", "home_id"),
                    ("securebase_refresh_sessions", "id"),
                    ("securebase_idempotency_keys", "key_hash"),
                    ("securebase_home_layouts", "home_id"),
                    ("securebase_optimization_runs", "id"),
                    ("securebase_optimization_solutions", "id"),
                    ("securebase_manual_configurations", "id"),
                ):
                    response = await client.get(
                        f"{self._base_url}/rest/v1/{table}",
                        headers=self._admin_headers(),
                        params={"select": column, "limit": "1"},
                    )
                    if not response.is_success:
                        return False
        except httpx.RequestError:
            return False
        return True

    async def _rpc(self, function: str, payload: dict[str, Any]) -> Any:
        try:
            async with self._client() as client:
                response = await client.post(
                    f"{self._base_url}/rest/v1/rpc/{function}",
                    headers=self._admin_headers(),
                    json=payload,
                )
        except httpx.RequestError as exc:
            raise Problem(
                503,
                "DATABASE_UNAVAILABLE",
                "Serviço temporariamente indisponível",
                "Não foi possível acessar as contas. Tente novamente.",
            ) from exc
        if response.is_error:
            raise Problem(
                503,
                "DATABASE_UNAVAILABLE",
                "Serviço temporariamente indisponível",
                "Não foi possível acessar as contas. Tente novamente.",
            )
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise Problem(
                503,
                "INVALID_DATABASE_RESPONSE",
                "Serviço temporariamente indisponível",
                "O banco retornou uma resposta inválida.",
            ) from exc

    async def _request(
        self,
        method: str,
        *,
        table: str = "securebase_users",
        params: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        prefer: str | None = None,
        conflict_is_account: bool = False,
        conflict_is_membership: bool = False,
        conflict: Problem | None = None,
    ) -> list[dict[str, Any]]:
        headers = self._admin_headers()
        if prefer:
            headers["Prefer"] = prefer
        try:
            async with self._client() as client:
                response = await client.request(
                    method,
                    f"{self._base_url}/rest/v1/{table}",
                    headers=headers,
                    params=params,
                    json=payload,
                )
        except httpx.RequestError as exc:
            raise Problem(
                503,
                "DATABASE_UNAVAILABLE",
                "Serviço temporariamente indisponível",
                "Não foi possível acessar as contas. Tente novamente.",
            ) from exc

        if conflict_is_account and response.status_code == 409:
            raise Problem(
                409,
                "ACCOUNT_CONFLICT",
                "Conflito",
                "Já existe uma conta com este e-mail.",
            )
        if conflict_is_membership and response.status_code == 409:
            raise Problem(
                409,
                "HOME_MEMBER_CONFLICT",
                "Conflito",
                "Este usuário já pertence à residência.",
            )
        if conflict is not None and response.status_code == 409:
            raise conflict
        if response.is_error:
            raise Problem(
                503,
                "DATABASE_UNAVAILABLE",
                "Serviço temporariamente indisponível",
                "Não foi possível acessar as contas. Tente novamente.",
            )
        if response.status_code == 204 or not response.content:
            return []
        try:
            result = response.json()
        except ValueError as exc:
            raise Problem(
                503,
                "INVALID_DATABASE_RESPONSE",
                "Serviço temporariamente indisponível",
                "O banco retornou uma resposta inválida.",
            ) from exc
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise Problem(
                503,
                "INVALID_DATABASE_RESPONSE",
                "Serviço temporariamente indisponível",
                "O banco retornou uma resposta inesperada.",
            )
        return result

    @staticmethod
    def to_profile(payload: dict[str, Any]) -> UserProfile:
        try:
            return UserProfile(
                id=payload["id"],
                email=payload["email"],
                name=payload["full_name"],
                role=Role(payload["role"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise Problem(
                503,
                "INVALID_PROFILE_DATA",
                "Perfil indisponível",
                "Os dados do perfil estão incompletos ou inválidos.",
            ) from exc


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _layout_conflict() -> Problem:
    return Problem(
        409,
        "LAYOUT_VERSION_CONFLICT",
        "Conflito de versão",
        "O layout foi alterado por outra pessoa. Recarregue e aplique suas mudanças novamente.",
    )


def _unconfirmed(subject: str) -> Problem:
    return Problem(
        503,
        "INVALID_DATABASE_RESPONSE",
        "Serviço temporariamente indisponível",
        f"O banco não confirmou a gravação de {subject}.",
    )
