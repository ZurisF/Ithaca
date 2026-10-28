"""Authenticated, content-free trace ingestion from the local runtime."""

import hmac
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import AppError
from app.observability.trace import PostgresTraceSink
from app.settings import get_settings
from model_adapter import TraceSpan

router = APIRouter(prefix="/internal/v1", tags=["internal"])


def require_desktop_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().desktop_instance_token
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not expected or not hmac.compare_digest(supplied, expected):
        raise AppError(401, "unauthenticated", "本地运行时需要桌面实例授权。")


class ModelTraceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trace_id: UUID
    session_id: UUID | None
    operation_name: str = Field(min_length=1, max_length=100)
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    prompt_version: str | None = Field(default=None, max_length=100)
    status: Literal["succeeded", "failed"]
    attempt_no: int = Field(ge=1)
    started_at: datetime
    finished_at: datetime
    latency_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=100)


@router.post("/model-traces", status_code=202, dependencies=[Depends(require_desktop_token)])
async def ingest_model_trace(body: ModelTraceRequest) -> dict[str, str]:
    await PostgresTraceSink().write(TraceSpan(**body.model_dump()))
    return {"status": "accepted"}
