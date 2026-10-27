from fastapi import APIRouter

from modules.auth.dependencies import Repository
from modules.controller.health_controller import live, ready
from modules.schemas.health_schemas import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])
router.add_api_route("/live", live, methods=["GET"], response_model=HealthResponse)


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={
        503: {
            "description": "Banco de dados indisponível",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/Problem"},
                    "example": {
                        "type": "urn:securebase:problem:database-unavailable",
                        "title": "Banco de dados indisponível",
                        "status": 503,
                        "detail": "O banco de dados ou o schema necessário não está pronto.",
                        "instance": "/health/ready",
                        "code": "DATABASE_UNAVAILABLE",
                        "traceId": "00000000-0000-4000-8000-000000000000",
                    },
                },
            },
        },
    },
)
async def readiness(
    repository: Repository,
) -> HealthResponse:
    return await ready(repository)
