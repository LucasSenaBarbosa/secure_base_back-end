from fastapi import APIRouter, Request

from modules.schemas.root_schemas import RootResponse

router = APIRouter(tags=["root"])


@router.get("/", response_model=RootResponse)
async def root(request: Request) -> RootResponse:
    return RootResponse(
        name=request.app.title,
        version=request.app.version,
        status="online",
        documentation="/docs",
    )
