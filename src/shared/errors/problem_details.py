import logging
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException


class ProblemDetails(BaseModel):
    model_config = ConfigDict(title="Problem", populate_by_name=True)

    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    trace_id: str | None = Field(alias="traceId")
    fields: list[str] | None = None


@dataclass
class Problem(Exception):
    status: int
    code: str
    title: str
    detail: str
    headers: dict[str, str] = field(default_factory=dict)


async def problem_handler(request: Request, exc: Problem) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        media_type="application/problem+json",
        headers=exc.headers,
        content={
            "type": f"urn:securebase:problem:{exc.code.lower()}",
            "title": exc.title,
            "status": exc.status,
            "detail": exc.detail,
            "instance": request.url.path,
            "code": exc.code,
            "traceId": getattr(request.state, "request_id", None),
        },
    )


async def validation_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    fields = sorted(
        {
            ".".join(str(part) for part in error["loc"] if part != "body")
            for error in exc.errors()
        }
    )
    return JSONResponse(
        status_code=422,
        media_type="application/problem+json",
        content={
            "type": "urn:securebase:problem:validation-error",
            "title": "Erro de validação",
            "status": 422,
            "detail": "Um ou mais campos da requisição são inválidos.",
            "instance": request.url.path,
            "code": "VALIDATION_ERROR",
            "fields": fields,
            "traceId": getattr(request.state, "request_id", None),
        },
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    code, title, detail = {
        400: ("BAD_REQUEST", "Requisição inválida", "A requisição não pôde ser processada."),
        401: ("AUTHENTICATION_REQUIRED", "Não autenticado", "Autentique-se e tente novamente."),
        403: ("FORBIDDEN", "Acesso negado", "Você não tem permissão para esta operação."),
        404: ("NOT_FOUND", "Não encontrado", "O recurso solicitado não existe."),
        405: (
            "METHOD_NOT_ALLOWED",
            "Método não permitido",
            "O método HTTP não é permitido nesta rota.",
        ),
    }.get(
        exc.status_code,
        ("HTTP_ERROR", "Erro HTTP", "A requisição não pôde ser processada."),
    )
    return await problem_handler(
        request,
        Problem(exc.status_code, code, title, detail, headers=exc.headers or {}),
    )


async def internal_error_handler(request: Request, _exc: Exception) -> JSONResponse:
    logging.getLogger("securebase.request").exception(
        "unhandled_request_error",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "path": request.url.path,
        },
    )
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=500,
        media_type="application/problem+json",
        headers={"X-Request-ID": request_id} if request_id else {},
        content={
            "type": "urn:securebase:problem:internal-error",
            "title": "Erro interno",
            "status": 500,
            "detail": "Ocorreu um erro inesperado. Tente novamente.",
            "instance": request.url.path,
            "code": "INTERNAL_ERROR",
            "traceId": request_id,
        },
    )
