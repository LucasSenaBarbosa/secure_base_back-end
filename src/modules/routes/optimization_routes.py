from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from modules.auth.dependencies import Repository
from modules.auth.middleware import HomeAdminUser, HomeMemberUser
from modules.controller import optimization_controller
from modules.schemas.optimization_schemas import (
    CompareRequest,
    Comparison,
    Evaluation,
    EvaluationRequest,
    LayoutDocument,
    ManualConfiguration,
    ManualConfigurationRequest,
    OptimizationRunRequest,
    RunDetail,
    RunSummary,
    SaveLayoutRequest,
    SolutionDetail,
)
from modules.service.idempotency_service import execute_idempotently

router = APIRouter(prefix="/homes/{home_id}", tags=["optimization"])
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
_ADMIN = {"s403": "Exige primary da residência ou master", "s404": "Residência não encontrada"}
_LAYOUT_NEEDED = (
    "`LAYOUT_REQUIRED` (layout não salvo) ou `LAYOUT_INCOMPLETE` (orçamento ou custos vazios)"
)


@router.get(
    "/layout",
    response_model=LayoutDocument,
    summary="Obter o layout da residência",
    description=(
        "Retorna o layout salvo (`source: saved`) ou, se ainda não houver, o layout-base da "
        "maquete (`source: template`, `version: 0`) com orçamento e custos vazios."
    ),
    responses=_problems(**_MEMBER),
)
async def get_layout(
    home_id: UUID,
    _: HomeMemberUser,
    repository: Repository,
) -> LayoutDocument:
    return await optimization_controller.get_layout(home_id, repository)


@router.put(
    "/layout",
    response_model=LayoutDocument,
    summary="Salvar o layout da residência",
    description=(
        "Substitui o layout inteiro. Envie em `version` a versão lida (0 no primeiro "
        "salvamento); versões divergentes respondem `409 LAYOUT_VERSION_CONFLICT`."
    ),
    responses=_problems(**_ADMIN, s409="`LAYOUT_VERSION_CONFLICT`"),
)
async def save_layout(
    home_id: UUID,
    payload: SaveLayoutRequest,
    actor: HomeAdminUser,
    repository: Repository,
) -> LayoutDocument:
    return await optimization_controller.save_layout(home_id, payload, actor, repository)


@router.post(
    "/configurations/evaluate",
    response_model=Evaluation,
    summary="Avaliar uma configuração de sensores",
    description=(
        "Calcula cobertura, custo, vulnerabilidade e restrições de uma configuração contra "
        "o layout salvo, sem gravar nada."
    ),
    responses=_problems(
        **_MEMBER,
        s409=_LAYOUT_NEEDED,
        s422="Dados inválidos ou `INVALID_SENSOR_PLACEMENT`",
    ),
)
async def evaluate_configuration(
    home_id: UUID,
    payload: EvaluationRequest,
    _: HomeMemberUser,
    repository: Repository,
) -> Evaluation:
    return await optimization_controller.evaluate_configuration(home_id, payload, repository)


@router.post(
    "/optimization-runs",
    response_model=RunDetail,
    status_code=201,
    summary="Executar a otimização NSGA-II",
    description=(
        "Executa o NSGA-II sobre o layout salvo e grava a execução com as soluções viáveis e "
        "não dominadas. A resposta não elege uma solução como a melhor."
    ),
    responses=_problems(
        **_ADMIN,
        s409=_LAYOUT_NEEDED + " ou conflito de idempotência",
        s503="`OPTIMIZATION_BUSY`, `OPTIMIZATION_TIMEOUT` ou banco indisponível",
    ),
)
async def run_optimization(
    home_id: UUID,
    payload: OptimizationRunRequest,
    actor: HomeAdminUser,
    repository: Repository,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> RunDetail:
    async def operation() -> tuple[RunDetail, int]:
        result = await optimization_controller.run_optimization(
            home_id,
            payload,
            actor,
            repository,
        )
        return result, 201

    return await execute_idempotently(
        key=idempotency_key,
        scope=f"optimization-run:{actor.id}:{home_id}",
        request_model=payload,
        response_model=RunDetail,
        response=response,
        repository=repository,
        operation=operation,
    )


@router.get(
    "/optimization-runs",
    response_model=list[RunSummary],
    summary="Listar otimizações",
    responses=_problems(**_MEMBER),
)
async def list_runs(
    home_id: UUID,
    _: HomeMemberUser,
    repository: Repository,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[RunSummary]:
    return await optimization_controller.list_runs(home_id, limit, offset, repository)


@router.get(
    "/optimization-runs/{run_id}",
    response_model=RunDetail,
    summary="Detalhar uma otimização",
    description="Inclui o layout usado na execução e a fronteira de Pareto.",
    responses=_problems(**_MEMBER),
)
async def get_run(
    home_id: UUID,
    run_id: UUID,
    _: HomeMemberUser,
    repository: Repository,
) -> RunDetail:
    return await optimization_controller.get_run(home_id, run_id, repository)


@router.get(
    "/optimization-runs/{run_id}/solutions/{solution_id}",
    response_model=SolutionDetail,
    summary="Detalhar uma solução",
    description="Inclui a probabilidade de detecção de cada ponto crítico.",
    responses=_problems(**_MEMBER),
)
async def get_solution(
    home_id: UUID,
    run_id: UUID,
    solution_id: UUID,
    _: HomeMemberUser,
    repository: Repository,
) -> SolutionDetail:
    return await optimization_controller.get_solution(home_id, run_id, solution_id, repository)


@router.post(
    "/optimization-runs/{run_id}/compare",
    response_model=Comparison,
    summary="Comparar configuração manual com as soluções",
    description=(
        "Avalia a configuração manual com o mesmo layout da execução e indica, para cada "
        "solução, as diferenças e a relação de dominância de Pareto."
    ),
    responses=_problems(**_MEMBER, s422="Dados inválidos ou `INVALID_SENSOR_PLACEMENT`"),
)
async def compare(
    home_id: UUID,
    run_id: UUID,
    payload: CompareRequest,
    _: HomeMemberUser,
    repository: Repository,
) -> Comparison:
    return await optimization_controller.compare(home_id, run_id, payload, repository)


@router.get(
    "/manual-configurations",
    response_model=list[ManualConfiguration],
    summary="Listar configurações manuais",
    description="As métricas são recalculadas contra o layout salvo atual.",
    responses=_problems(**_MEMBER),
)
async def list_manual_configurations(
    home_id: UUID,
    _: HomeMemberUser,
    repository: Repository,
) -> list[ManualConfiguration]:
    return await optimization_controller.list_manual_configurations(home_id, repository)


@router.post(
    "/manual-configurations",
    response_model=ManualConfiguration,
    status_code=201,
    summary="Salvar configuração manual",
    responses=_problems(
        **_ADMIN,
        s409="`LAYOUT_REQUIRED` ou conflito de idempotência",
        s422="Dados inválidos ou `INVALID_SENSOR_PLACEMENT`",
    ),
)
async def create_manual_configuration(
    home_id: UUID,
    payload: ManualConfigurationRequest,
    actor: HomeAdminUser,
    repository: Repository,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> ManualConfiguration:
    async def operation() -> tuple[ManualConfiguration, int]:
        result = await optimization_controller.create_manual_configuration(
            home_id,
            payload,
            actor,
            repository,
        )
        return result, 201

    return await execute_idempotently(
        key=idempotency_key,
        scope=f"manual-configuration:{actor.id}:{home_id}",
        request_model=payload,
        response_model=ManualConfiguration,
        response=response,
        repository=repository,
        operation=operation,
    )


@router.delete(
    "/manual-configurations/{configuration_id}",
    status_code=204,
    response_class=Response,
    summary="Remover configuração manual",
    responses=_problems(**_ADMIN),
)
async def delete_manual_configuration(
    home_id: UUID,
    configuration_id: UUID,
    _: HomeAdminUser,
    repository: Repository,
) -> Response:
    await optimization_controller.delete_manual_configuration(
        home_id,
        configuration_id,
        repository,
    )
    return Response(status_code=204)
