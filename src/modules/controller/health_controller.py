from modules.repository.supabase_repository import SupabaseRepository
from modules.schemas.health_schemas import HealthResponse
from modules.service.health_service import dependencies_are_ready
from shared.errors.problem_details import Problem


async def live() -> HealthResponse:
    return HealthResponse(status="ok")


async def ready(
    repository: SupabaseRepository,
) -> HealthResponse:
    if not await dependencies_are_ready(repository):
        raise Problem(
            503,
            "DATABASE_UNAVAILABLE",
            "Banco de dados indisponível",
            "O banco de dados ou o schema necessário não está pronto.",
        )
    return HealthResponse(status="ok")
