"""Configuracion centralizada del sistema."""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Base de datos
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/sistema_endeudamiento"

    # Seguridad
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 horas

    # App
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    APP_TITLE: str = "Sistema de Endeudamiento - VP Finanzas"
    APP_VERSION: str = "1.0.0"
    API_PREFIX: str = "/api/v1"

    # CORS
    FRONTEND_URL: str = "http://localhost:5173"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # Tope de endeudamiento (USD millones)
    DEBT_CEILING_USD_MM: float = 2500.0

    # Railway port
    PORT: int = 8000

    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
