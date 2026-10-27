import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import Response
from pydantic import BaseModel

from modules.repository.supabase_repository import SupabaseRepository
from shared.errors.problem_details import Problem

Model = TypeVar("Model", bound=BaseModel)


async def execute_idempotently(
    *,
    key: str,
    scope: str,
    request_model: BaseModel,
    response_model: type[Model],
    response: Response,
    repository: SupabaseRepository,
    operation: Callable[[], Awaitable[tuple[Model, int]]],
) -> Model:
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    request_hash = hashlib.sha256(
        json.dumps(
            request_model.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    claim = await repository.claim_idempotency(scope, key_hash, request_hash)

    if claim["state"] == "replay":
        response.status_code = int(claim["status_code"])
        response.headers["Idempotency-Replayed"] = "true"
        return response_model.model_validate(claim["response_body"])
    if claim["state"] == "conflict":
        raise Problem(
            409,
            "IDEMPOTENCY_KEY_REUSED",
            "Chave de idempotência reutilizada",
            "Use uma chave diferente para uma requisição com dados diferentes.",
        )
    if claim["state"] == "in_progress":
        raise Problem(
            409,
            "IDEMPOTENCY_IN_PROGRESS",
            "Requisição em andamento",
            "Aguarde a conclusão e repita a requisição com a mesma chave.",
            headers={"Retry-After": "2"},
        )

    try:
        result, status_code = await operation()
    except Problem:
        await repository.release_idempotency(scope, key_hash, request_hash)
        raise

    body = result.model_dump(mode="json")
    await repository.complete_idempotency(
        scope,
        key_hash,
        request_hash,
        status_code,
        body,
    )
    response.status_code = status_code
    return result
