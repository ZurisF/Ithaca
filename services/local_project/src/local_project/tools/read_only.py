"""Open relative files beneath an authorized root without following symlinks."""

import os
import stat
from pathlib import Path, PurePosixPath

from content_safety import ContentRejected, filter_text
from local_project.errors import LocalError

MAX_FILE_BYTES = 256_000
HARD_EXCLUDED = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".env",
        ".aws",
        ".ssh",
        ".gnupg",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        ".next",
        "coverage",
    }
)


def is_sensitive_path(components: tuple[str, ...]) -> bool:
    return any(
        name in HARD_EXCLUDED or name.startswith(".env") or name.endswith((".pem", ".key"))
        for name in (part.casefold() for part in components)
    )


def read_file_text(root: Path, relative_path: str) -> str:
    """Return only filtered text from an authorized, bounded regular file."""
    relative = PurePosixPath(relative_path)
    components = relative.parts
    if (
        relative.is_absolute()
        or not components
        or any(part in {".", "..", ""} for part in components)
    ):
        raise LocalError(400, "invalid_request", "只能读取授权目录内的相对路径。")
    if is_sensitive_path(components):
        raise LocalError(400, "source_file_rejected", "敏感路径不允许读取。")

    descriptors: list[int] = []
    try:
        current = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(current)
        for component in components[:-1]:
            current = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current
            )
            descriptors.append(current)
        file_descriptor = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current)
        descriptors.append(file_descriptor)
        file_stat = os.fstat(file_descriptor)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_FILE_BYTES:
            raise LocalError(400, "source_file_rejected", "文件类型或大小不允许读取。")
        raw = os.read(file_descriptor, MAX_FILE_BYTES + 1)
        if b"\x00" in raw:
            raise LocalError(400, "source_file_rejected", "二进制文件不允许读取。")
        try:
            lines = raw.decode("utf-8", errors="strict").splitlines()
        except UnicodeDecodeError as exc:
            raise LocalError(400, "source_file_rejected", "文件编码不受支持。") from exc
        content = "\n".join(lines)
        try:
            return filter_text(content, max_chars=MAX_FILE_BYTES).text if content.strip() else ""
        except ContentRejected as exc:
            raise LocalError(400, "source_file_rejected", "文件内容不允许读取。") from exc
    except OSError as exc:
        raise LocalError(400, "source_file_rejected", "文件已变化或不在授权目录内。") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def read_file_range(root: Path, relative_path: str, first_line: int, last_line: int) -> str:
    if first_line < 1 or last_line < first_line or last_line - first_line > 200:
        raise LocalError(400, "invalid_request", "行号范围无效。")
    lines = read_file_text(root, relative_path).splitlines()
    return "\n".join(lines[first_line - 1 : last_line])
