from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services.errors import AppError


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool = False


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorEnvelope(
            error=ErrorDetail(code=exc.code, message=exc.message, retryable=exc.retryable)
        ).model_dump(),
    )
