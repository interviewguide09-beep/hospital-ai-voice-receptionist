from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.api.v1.router import api_router
from app.core.logging import logger

def create_app() -> FastAPI:
    """Application factory for configuring and returning the FastAPI app instance."""
    # Ensure all models are registered and compiled in SQLAlchemy metadata
    from app.database import base
    
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

    # WhatsApp webhook — patient intake conversation replies
    from app.api.v1.endpoints import whatsapp_webhook
    app.include_router(whatsapp_webhook.router)

    # 4. Root Health Check Endpoint
    @app.get("/health", tags=["system"])
    async def health_check():
        """Basic service status check API."""
        return {
            "status": "healthy",
            "environment": settings.ENV,
            "project": settings.PROJECT_NAME
        }

    # 5. Serve React compiled frontend assets in production
    import os
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    # Resolve absolute path to frontend/dist
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    frontend_dist = os.path.join(base_dir, "frontend", "dist")

    if os.path.exists(frontend_dist):
        assets_path = os.path.join(frontend_dist, "assets")
        if os.path.exists(assets_path):
            app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

        # Catch-all endpoint for UI pages (directs to React SPA)
        @app.get("/{catchall:path}", include_in_schema=False)
        async def serve_react_app(catchall: str):
            index_path = os.path.join(frontend_dist, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path)
            return {"detail": "Frontend build files not found. Run npm run build."}

    logger.info("FastAPI application instance successfully created and configured.")
    return app

app = create_app()
