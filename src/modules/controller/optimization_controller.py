from uuid import UUID

from modules.repository.supabase_repository import SupabaseRepository
from modules.schemas.auth_schemas import UserProfile
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
from modules.service import optimization_service


async def get_layout(home_id: UUID, repository: SupabaseRepository) -> LayoutDocument:
    return await optimization_service.get_layout(home_id, repository)


async def save_layout(
    home_id: UUID,
    payload: SaveLayoutRequest,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> LayoutDocument:
    return await optimization_service.save_layout(home_id, payload, actor, repository)


async def evaluate_configuration(
    home_id: UUID,
    payload: EvaluationRequest,
    repository: SupabaseRepository,
) -> Evaluation:
    return await optimization_service.evaluate_configuration(home_id, payload, repository)


async def run_optimization(
    home_id: UUID,
    payload: OptimizationRunRequest,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> RunDetail:
    return await optimization_service.run_optimization(home_id, payload, actor, repository)


async def list_runs(
    home_id: UUID,
    limit: int,
    offset: int,
    repository: SupabaseRepository,
) -> list[RunSummary]:
    return await optimization_service.list_runs(home_id, limit, offset, repository)


async def get_run(home_id: UUID, run_id: UUID, repository: SupabaseRepository) -> RunDetail:
    return await optimization_service.get_run(home_id, run_id, repository)


async def get_solution(
    home_id: UUID,
    run_id: UUID,
    solution_id: UUID,
    repository: SupabaseRepository,
) -> SolutionDetail:
    return await optimization_service.get_solution(home_id, run_id, solution_id, repository)


async def compare(
    home_id: UUID,
    run_id: UUID,
    payload: CompareRequest,
    repository: SupabaseRepository,
) -> Comparison:
    return await optimization_service.compare(home_id, run_id, payload, repository)


async def create_manual_configuration(
    home_id: UUID,
    payload: ManualConfigurationRequest,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> ManualConfiguration:
    return await optimization_service.create_manual_configuration(
        home_id,
        payload,
        actor,
        repository,
    )


async def list_manual_configurations(
    home_id: UUID,
    repository: SupabaseRepository,
) -> list[ManualConfiguration]:
    return await optimization_service.list_manual_configurations(home_id, repository)


async def delete_manual_configuration(
    home_id: UUID,
    configuration_id: UUID,
    repository: SupabaseRepository,
) -> None:
    await optimization_service.delete_manual_configuration(home_id, configuration_id, repository)
