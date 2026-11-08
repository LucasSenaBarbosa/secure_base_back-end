from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from modules.auth.dependencies import Repository
from modules.auth.middleware import HomeMemberUser
from modules.controller import link_simulation_controller
from modules.schemas.link_simulation_schemas import (
    LinkCatalog,
    LinkSimulationDetail,
    LinkSimulationRequest,
    LinkSimulationSummary,
)
from modules.service.idempotency_service import execute_idempotently

router = APIRouter(prefix="/homes/{home_id}/link-simulations", tags=["link-simulations"])
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=200),
]


def _problems(**descriptions: str) -> dict[int | str, dict[str, Any]]:
    return {
        int(status.removeprefix("s")): {
            "description": description,
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/Problem"},
                },
            },
        }
        for status, description in descriptions.items()
    }


_MEMBER = {"s403": "Sem participação na residência", "s404": "Residência não encontrada"}


@router.get(
    "/catalog",
    response_model=LinkCatalog,
    summary="Listar cenários e defesas",
    description="Catálogo do laboratório de rede, com as aulas relacionadas a cada item.",
    responses=_problems(**_MEMBER),
)
async def get_catalog(home_id: UUID, _: HomeMemberUser) -> LinkCatalog:
    return link_simulation_controller.get_catalog()


@router.post(
    "",
    response_model=LinkSimulationDetail,
    status_code=201,
    summary="Simular o envio de um alerta",
    description=(
        "Simula o caminho do alerta sob o cenário escolhido e grava o resultado no histórico. "
        "A resposta traz também as métricas do mesmo cenário sem defesas. Nenhum sinal ou "
        "tráfego real é gerado."
    ),
    responses=_problems(**_MEMBER, s409="Conflito de idempotência"),
)
async def create_simulation(
    home_id: UUID,
    payload: LinkSimulationRequest,
    actor: HomeMemberUser,
    repository: Repository,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> LinkSimulationDetail:
    async def operation() -> tuple[LinkSimulationDetail, int]:
        result = await link_simulation_controller.create_simulation(
            home_id,
            payload,
            actor,
            repository,
        )
        return result, 201

    return await execute_idempotently(
        key=idempotency_key,
        scope=f"link-simulation:{actor.id}:{home_id}",
        request_model=payload,
        response_model=LinkSimulationDetail,
        response=response,
        repository=repository,
        operation=operation,
    )


@router.get(
    "",
    response_model=list[LinkSimulationSummary],
    summary="Listar simulações de rede",
    responses=_problems(**_MEMBER),
)
async def list_simulations(
    home_id: UUID,
    _: HomeMemberUser,
    repository: Repository,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[LinkSimulationSummary]:
    return await link_simulation_controller.list_simulations(home_id, limit, offset, repository)


@router.get(
    "/{simulation_id}",
    response_model=LinkSimulationDetail,
    summary="Detalhar uma simulação de rede",
    responses=_problems(**_MEMBER),
)
async def get_simulation(
    home_id: UUID,
    simulation_id: UUID,
    _: HomeMemberUser,
    repository: Repository,
) -> LinkSimulationDetail:
    return await link_simulation_controller.get_simulation(home_id, simulation_id, repository)
