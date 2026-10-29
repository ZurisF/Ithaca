import logging
from typing import Annotated
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.errors import AppError, ErrorEnvelope, app_error_handler
from app.api.identity import Identity, get_identity
from app.api.internal import router as internal_router
from app.api.interview import router as interview_router
from app.api.prepare import router as prepare_router
from app.db import engine
from app.domain.contracts import ModelReadiness
from app.observability.logging import configure_logging
from app.settings import get_settings

configure_logging()
settings = get_settings()
app = FastAPI(title="Project Interview Lab Application", version="0.1.0")
app.add_exception_handler(AppError, app_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error": {"code": "invalid_request", "message": "请求格式无效。", "retryable": False}
        },
    )


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {"code": "invalid_request", "message": "请求无法处理。", "retryable": False}
        },
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-Dev-User"],
)
app.include_router(prepare_router)
app.include_router(interview_router)
app.include_router(internal_router)


@app.get("/health", responses={503: {"model": ErrorEnvelope}})
async def health() -> JSONResponse:
    dependencies: dict[str, str] = {}
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        dependencies["postgresql"] = "ok"
    except Exception:  # noqa: BLE001 - health must survive any dependency failure
        dependencies["postgresql"] = "unavailable"
    redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        await redis.ping()
        dependencies["redis"] = "ok"
    except Exception:  # noqa: BLE001 - health must survive any dependency failure
        dependencies["redis"] = "unavailable"
    finally:
        await redis.aclose()
    ready = all(value == "ok" for value in dependencies.values())
    if not ready:
        logging.getLogger(__name__).warning("health_dependency_unavailable")
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "runtime": "application",
            "process": "running",
            "status": "ready" if ready else "degraded",
            "dependencies": dependencies,
        },
    )


@app.get(
    "/v1/model-readiness",
    response_model=ModelReadiness,
    responses={503: {"model": ErrorEnvelope}},
)
async def model_readiness() -> ModelReadiness:
    if not settings.model_api_key or not settings.model_name:
        raise AppError(503, "dependency_unavailable", "模型尚未配置。", retryable=False)
    return ModelReadiness(
        status="configured",
        model=settings.model_name,
        provider_host=urlparse(settings.model_base_url).hostname or "未知服务",
    )


@app.get("/v1/me")
async def current_identity(
    identity: Annotated[Identity, Depends(get_identity)],
) -> dict[str, str | None]:
    return {"id": str(identity.id), "role": identity.role, "display_name": identity.display_name}
