from fastapi import APIRouter
from app.api.v1.endpoints import voice, appointments

api_router = APIRouter()

# Register Twilio call voice stream routes
api_router.include_router(voice.router, prefix="/voice", tags=["voice"])

# Register Dashboard / Admin console routes
api_router.include_router(appointments.router, tags=["appointments"])
