from fastapi import Request
from fastapi.responses import JSONResponse


class LocalError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


async def local_error_handler(_request: Request, exc: LocalError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "retryable": False}},
    )
