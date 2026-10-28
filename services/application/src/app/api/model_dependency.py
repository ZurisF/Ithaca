from app.observability.trace import PostgresTraceSink
from app.settings import get_settings
from model_adapter import ModelAdapter, OpenAICompatibleAdapter


def get_model_adapter() -> ModelAdapter:
    settings = get_settings()
    return OpenAICompatibleAdapter(
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        model=settings.model_name,
        provider=settings.model_provider,
        trace_sink=PostgresTraceSink(),
        max_concurrency=settings.model_max_concurrency,
    )
