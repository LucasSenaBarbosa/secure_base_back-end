from uuid import UUID

from modules.repository.supabase_repository import SupabaseRepository
from modules.schemas.auth_schemas import UserProfile
from modules.schemas.link_simulation_schemas import (
    LinkCatalog,
    LinkSimulationDetail,
    LinkSimulationRequest,
    LinkSimulationSummary,
)
from modules.service import link_simulation_service


def get_catalog() -> LinkCatalog:
    return link_simulation_service.get_catalog()


async def create_simulation(
    home_id: UUID,
    payload: LinkSimulationRequest,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> LinkSimulationDetail:
    return await link_simulation_service.create_simulation(home_id, payload, actor, repository)


async def list_simulations(
    home_id: UUID,
    limit: int,
    offset: int,
    repository: SupabaseRepository,
) -> list[LinkSimulationSummary]:
    return await link_simulation_service.list_simulations(home_id, limit, offset, repository)


async def get_simulation(
    home_id: UUID,
    simulation_id: UUID,
    repository: SupabaseRepository,
) -> LinkSimulationDetail:
    return await link_simulation_service.get_simulation(home_id, simulation_id, repository)
