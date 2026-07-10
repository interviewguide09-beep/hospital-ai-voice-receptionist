from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.api.v1.router import api_router
from app.core.logging import logger

def create_app() -> FastAPI:
    """Application factory for configuring and returning the FastAPI app instance."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        description="Production API backend managing Twilio Voice and Gemini live connections for Hospital AI Receptionists.",
        version="1.0.0"
    )

    # 1. Register Global CORS Middleware
    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # 2. Register custom application exceptions mapping handlers
    register_exception_handlers(app)

    # 3. Include API v1 Router prefix
    app.include_router(api_router, prefix=settings.API_V1_STR)

    # Include appointments router at root level so dashboard works at /receptionist/schedule directly
    from app.api.v1.endpoints import appointments
    app.include_router(appointments.router)

    # 4. Root Health Check Endpoint
    @app.get("/health", tags=["system"])
    async def health_check():
        """Basic service status check API."""
        return {
            "status": "healthy",
            "environment": settings.ENV,
            "project": settings.PROJECT_NAME
        }

    logger.info("FastAPI application instance successfully created and configured.")
    return app

app = create_app()
