"""Process-local source authorization registry; paths never cross runtime boundaries."""

import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from local_project.errors import LocalError

HANDLE_TTL_SECONDS = 60 * 60


@dataclass
class SourceGrant:
    session_id: UUID
    root: Path
    expires_at: float


class SourceRegistry:
    def __init__(self) -> None:
        self._grants: dict[str, SourceGrant] = {}

    def authorize(self, session_id: UUID, raw_path: str) -> str:
        requested = Path(raw_path)
        if not requested.is_absolute():
            raise LocalError(400, "invalid_request", "请选择绝对目录路径。")
        try:
            root = requested.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise LocalError(400, "invalid_request", "所选目录不可访问。") from exc
        if not root.is_dir():
            raise LocalError(400, "invalid_request", "请选择目录。")
        handle = secrets.token_urlsafe(32)
        self._grants[handle] = SourceGrant(session_id, root, time.monotonic() + HANDLE_TTL_SECONDS)
        return handle

    def get(self, handle: str, session_id: UUID) -> Path:
        grant = self._grants.get(handle)
        if grant is None or grant.session_id != session_id or grant.expires_at < time.monotonic():
            raise LocalError(404, "source_not_found", "目录授权已失效或不属于当前会话。")
        grant.expires_at = time.monotonic() + HANDLE_TTL_SECONDS
        return grant.root

    def release(self, handle: str, session_id: UUID) -> None:
        self.get(handle, session_id)
        self._grants.pop(handle, None)


registry = SourceRegistry()
