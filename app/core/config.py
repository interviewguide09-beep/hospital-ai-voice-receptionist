import os
from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    # Project Core Configurations
    PROJECT_NAME: str = "Hospital AI Voice Receptionist"
    ENV: str = "production"  # development, staging, production
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"

    # MySQL Database Settings (SQLAlchemy & Alembic compatibility)
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DATABASE: str = "hospital_voice_db"

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """Constructs the async mysql database url."""
        return f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Constructs the sync mysql database url (for migrations)."""
        return f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"

    # JWT Authentication Configurations
    JWT_SECRET_KEY: str = "SECRET_MUST_BE_REPLACED_IN_PRODUCTION_ENV_FILE"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 Hours

    # Gemini LLM API Configurations
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-1.5-flash-latest"

    # Twilio Voice Service Configurations
    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_PHONE_NUMBER: str
    TWILIO_WEBHOOK_URL: str  # Public webhook target (e.g. ngrok or production domain)
    TEST_PHONE_NUMBER: str = ""

    # WhatsApp Notification via Twilio WhatsApp API
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"
    RECEPTIONIST_WHATSAPP_NUMBER: str = ""

    # Payment Gateway — patient ke WhatsApp message mein yeh link aayega
    # Razorpay, Cashfree, PhonePe ya koi bhi payment page URL daal do
    PAYMENT_BASE_URL: str = "https://pay.cptiwari.com/appointment"

    # n8n Automation Service Configurations
    N8N_WEBHOOK_URL: str
    N8N_API_KEY: str = ""

    # Security Configuration
    BACKEND_CORS_ORIGINS: List[str] = ["*"]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

settings = Settings()
