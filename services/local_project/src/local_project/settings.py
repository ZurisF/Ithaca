from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOCAL_", env_file=".env", extra="ignore")

    desktop_instance_token: str = ""
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8101, ge=1, le=65535)
    app_runtime_url: str = "http://127.0.0.1:8100"
    model_api_key: str = Field(default="", validation_alias="APP_MODEL_API_KEY")
    model_name: str = Field(default="", validation_alias="APP_MODEL_NAME")
    model_base_url: str = Field(
        default="https://api.openai.com/v1", validation_alias="APP_MODEL_BASE_URL"
    )
    model_provider: str = Field(default="openai_compatible", validation_alias="APP_MODEL_PROVIDER")
    inventory_max_items: int = Field(default=2_000, ge=1, le=2_000)
    max_file_bytes: int = Field(default=256_000, ge=1_024, le=256_000)
    observer_map_files: int = Field(default=120, ge=1, le=500)
    observer_map_chars: int = Field(default=20_000, ge=1_000, le=100_000)
    observer_tool_steps: int = Field(default=10, ge=1, le=30)
    observer_total_chars: int = Field(default=60_000, ge=5_000, le=200_000)
    observer_search_files: int = Field(default=100, ge=1, le=100)
    observer_search_matches: int = Field(default=30, ge=1, le=30)
    observer_tool_chars: int = Field(default=8_000, ge=500, le=8_000)
    observer_max_prompt_bytes: int = Field(default=180_000, ge=20_000, le=1_000_000)
    observer_step_max_tokens: int = Field(default=4_096, ge=256, le=16_384)
    observer_total_model_tokens: int = Field(default=1_200_000, ge=50_000, le=10_000_000)
    observer_timeout_seconds: int = Field(default=180, ge=30, le=600)


@lru_cache
def get_settings() -> Settings:
    return Settings()
