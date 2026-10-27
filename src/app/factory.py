from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from starlette.exceptions import HTTPException as StarletteHTTPException

from config.settings import get_settings
from middleware import add_request_id
from modules.routes.routes import api_router
from shared.errors.problem_details import (
    Problem,
    ProblemDetails,
    http_exception_handler,
    internal_error_handler,
    problem_handler,
    validation_handler,
)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SecureBase API",
        version="0.1.0",
        description="API Python do SecureBase com autenticação própria e PostgreSQL.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-CSRF-Token",
            "X-Request-ID",
        ],
        expose_headers=["Idempotency-Replayed", "X-Request-ID"],
    )
    app.middleware("http")(add_request_id)
    app.add_exception_handler(Problem, problem_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, internal_error_handler)
    app.include_router(api_router)

    def custom_openapi() -> dict[str, object]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema.setdefault("components", {}).setdefault("schemas", {})[
            "Problem"
        ] = ProblemDetails.model_json_schema(by_alias=True)
        problem_response = {
            "description": "Erro no formato RFC 9457",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/Problem"},
                },
            },
        }
        for path_item in schema["paths"].values():
            for operation in path_item.values():
                if not isinstance(operation, dict) or "responses" not in operation:
                    continue
                responses = operation["responses"]
                responses.setdefault("default", problem_response)
                if "422" in responses:
                    responses["422"] = problem_response
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi
    return app
