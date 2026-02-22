from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: str = "development"
    DEBUG: bool = True

    # Auth
    AUTH_ENABLED: bool = False
    JWT_SECRET: str = "dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # Database
    DATABASE_URL: str = "mysql+asyncmy://ptm_user:ptm_password@localhost:3306/ptm_platform"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"

    # ChromaDB
    CHROMADB_URL: str = "http://localhost:8000"

    # Ollama
    OLLAMA_URL: str = "http://localhost:11434"
    DEFAULT_LLM_MODEL: str = "qwen2.5:7b"

    # MCP Server
    MCP_SERVER_URL: str = "http://localhost:8001"

    # File paths
    INPUT_DIR: str = "/app/data/inputs"
    OUTPUT_DIR: str = "/app/data/outputs"
    REPORTS_DIR: str = "/app/storage/reports"
    REFERENCE_DIR: str = "/app/data/reference"
    LOG_DIR: str = "/app/storage/logs"

    # Cloud LLM keys (optional)
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
