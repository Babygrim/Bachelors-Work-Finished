from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth.routes import router as auth_router
from .core.config import CORS_ORIGINS
from .core.errors import register_error_handlers
from .subscriptions.routes import router as subscription_router
from .upscaling.routes import router as upscale_router


def create_app() -> FastAPI:
    application = FastAPI(title="AI Upscaler API", version="2.0.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(application)
    application.include_router(auth_router)
    application.include_router(subscription_router)
    application.include_router(upscale_router)

    @application.get("/api/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "ai-upscaler-api"}

    return application


app = create_app()
