import hmac

from fastapi import Depends, FastAPI, Header

from local_project.api.sources import make_router
from local_project.errors import LocalError, local_error_handler
from local_project.logging import configure_logging
from local_project.settings import get_settings

configure_logging()
app = FastAPI(title="Project Interview Lab Local Project Runtime", version="0.1.0")
app.add_exception_handler(LocalError, local_error_handler)


def require_desktop_token(authorization: str | None = Header(default=None)) -> None:
    expected = get_settings().desktop_instance_token
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not expected or not hmac.compare_digest(supplied, expected):
        raise LocalError(401, "unauthenticated", "本地运行时需要桌面实例授权。")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"runtime": "local_project", "process": "running", "status": "ready"}


@app.get("/internal/v1/ready", dependencies=[Depends(require_desktop_token)])
async def internal_ready() -> dict[str, str]:
    return {"status": "ready"}


app.include_router(make_router(require_desktop_token))
