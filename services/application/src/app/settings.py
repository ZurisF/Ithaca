from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://interview:interview_dev_only@127.0.0.1:5432/interview_lab"
    )
    redis_url: str = "redis://127.0.0.1:6379/0"
    local_runtime_url: str = "http://127.0.0.1:8101"
    desktop_instance_token: str = ""
    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    dev_auth_enabled: bool = False
    model_api_key: str = ""
    model_name: str = ""
    model_base_url: str = "https://api.openai.com/v1"
    model_provider: str = "openai_compatible"
    model_timeout_seconds: int = Field(default=45, ge=1, le=300)
    model_max_attempts: int = Field(default=2, ge=1, le=5)
    model_max_concurrency: int = Field(default=4, ge=1, le=32)
    retrieval_limit: int = Field(default=3, ge=0, le=3)
    embedding_model_path: str = "BAAI/bge-m3"
    reranker_model_path: str = "BAAI/bge-reranker-base"
    retrieval_min_score: float = Field(default=0.1, ge=0, le=1)
    retrieval_timeout_seconds: int = Field(default=30, ge=1, le=180)
    retrieval_max_attempts: int = Field(default=2, ge=1, le=3)

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
