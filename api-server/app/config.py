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
    DB_CONNECT_MAX_ATTEMPTS: int = 60
    DB_CONNECT_RETRY_INITIAL_SEC: float = 1.0
    DB_CONNECT_RETRY_MAX_SEC: float = 5.0

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"

    # ChromaDB
    CHROMADB_URL: str = "http://localhost:8000"

    # Ollama
    OLLAMA_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "gemma3:27b"

    @property
    def DEFAULT_LLM_MODEL(self) -> str:  # noqa: N802
        return self.LLM_MODEL

    # MCP Server
    MCP_SERVER_URL: str = "http://localhost:8001"

    # Co-Scientist (container name used as DNS hostname inside ptm-platform-network)
    COSCIENTIST_API_URL: str = "http://ptm-coscientist-api:8080"

    # Cytoscape (Report network visualization)
    CYTOSCAPE_HOST: str = "host.docker.internal"
    CYTOSCAPE_PORT: int = 1234

    # File paths
    INPUT_DIR: str = "/app/data/inputs"
    OUTPUT_DIR: str = "/app/data/outputs"
    REPORTS_DIR: str = "/app/storage/reports"
    REFERENCE_DIR: str = "/app/data/reference"
    LOG_DIR: str = "/app/storage/logs"
    FILE_SHARE_DIR: str = "/app/storage/file_share"
    PTMQUANT_DIR: str = "/app/storage/ptmquant"
    # v0.5.3: shared AlphaPeptDeep predicted-library cache (container path).
    # Every PTMQuant job mounts this directory into the ptmquant container
    # and diaquant reuses cached libraries keyed by FASTA + PTM set +
    # instrument + enzyme + m/z range so the expensive AlphaPeptDeep
    # prediction runs at most once per (species, FASTA, PTMs) tuple.
    PTMQUANT_LIB_CACHE_DIR: str = "/app/storage/ptmquant/predicted_lib_cache"
    HOST_DATA_DIR: str = ""

    # PTMQuant Docker runner: if true, do not `docker rm` the job container when
    # diaquant exits non-zero — keeps `docker logs <id>` available for debugging.
    # Retrying the same job removes the stale container by name before recreate.
    PTMQUANT_KEEP_CONTAINER_ON_FAILURE: bool = False

    # Cloud LLM keys (optional)
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None

    # Webhook (order events)
    WEBHOOK_URL: str = ""

    # Email (notifications)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@ptm-platform.local"
    SMTP_USE_TLS: bool = True

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
