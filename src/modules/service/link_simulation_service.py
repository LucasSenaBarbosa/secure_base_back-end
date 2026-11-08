import secrets
from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from modules.repository.supabase_repository import SupabaseRepository
from modules.schemas.auth_schemas import UserProfile
from modules.schemas.link_simulation_schemas import (
    LinkCatalog,
    LinkSimulationDetail,
    LinkSimulationRequest,
    LinkSimulationSummary,
)
from modules.service import link_simulation_model as model
from modules.service.link_simulation_catalog import catalog
from shared.errors.problem_details import Problem


def get_catalog() -> LinkCatalog:
    return catalog()


async def create_simulation(
    home_id: UUID,
    payload: LinkSimulationRequest,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> LinkSimulationDetail:
    seed = payload.seed if payload.seed is not None else secrets.randbelow(2**31)
    outcome, without_defenses = model.simulate(
        payload.scenario,
        payload.intensity,
        payload.defenses,
        payload.trials,
        seed,
        payload.fake_generation,
    )
    row = await repository.create_link_simulation(
        {
            "id": str(uuid4()),
            "home_id": str(home_id),
            "created_by": str(actor.id),
            "scenario": payload.scenario,
            "intensity": payload.intensity,
            "defenses": payload.defenses,
            "trials": payload.trials,
            "seed": seed,
            "model_version": model.MODEL_VERSION,
            "verdict": outcome.metrics.verdict,
            "delivery_rate": outcome.metrics.delivery_rate,
            "result": {
                "metrics": asdict(outcome.metrics),
                "without_defenses": asdict(without_defenses),
                "hops": [asdict(hop) for hop in outcome.hops],
                "timeline": [asdict(event) for event in outcome.timeline],
                "fake_generation": payload.fake_generation,
                "cells": [asdict(cell) for cell in outcome.cells],
                "generations": [asdict(cell) for cell in outcome.generations],
            },
        }
    )
    return _detail(row)


async def list_simulations(
    home_id: UUID,
    limit: int,
    offset: int,
    repository: SupabaseRepository,
) -> list[LinkSimulationSummary]:
    rows = await repository.list_link_simulations(home_id, limit=limit, offset=offset)
    return [_parse(LinkSimulationSummary, row) for row in rows]


async def get_simulation(
    home_id: UUID,
    simulation_id: UUID,
    repository: SupabaseRepository,
) -> LinkSimulationDetail:
    row = await repository.get_link_simulation(home_id, simulation_id)
    if row is None:
        raise Problem(
            404,
            "LINK_SIMULATION_NOT_FOUND",
            "Não encontrada",
            "A simulação não existe nesta residência.",
        )
    return _detail(row)


def _detail(row: dict[str, Any]) -> LinkSimulationDetail:
    result = row.get("result")
    fields = {key: value for key, value in row.items() if key != "result"}
    return _parse(LinkSimulationDetail, {**fields, **(result if isinstance(result, dict) else {})})


def _parse[T: LinkSimulationSummary](schema: type[T], row: dict[str, Any]) -> T:
    try:
        return schema.model_validate(row)
    except ValidationError as exc:
        raise Problem(
            503,
            "INVALID_DATABASE_RESPONSE",
            "Serviço temporariamente indisponível",
            "O banco retornou uma simulação inválida.",
        ) from exc
