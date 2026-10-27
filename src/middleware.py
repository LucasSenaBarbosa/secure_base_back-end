from time import perf_counter
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.logging import request_logger


async def add_request_id(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    request.state.request_id = str(uuid4())
    started = perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    request_logger.info(
        "request_complete",
        extra={
            "request_id": request.state.request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
        },
    )
    return response
