import uvicorn

from app.factory import create_app
from config.settings import get_settings

app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment.lower() == "development",
    )
