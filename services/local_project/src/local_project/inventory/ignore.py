"""Evaluate root and nested .gitignore files without executing repository code."""

import os
import stat
from pathlib import Path

from pathspec import GitIgnoreSpec

from local_project.errors import LocalError

MAX_IGNORE_BYTES = 64_000


def load_rules(
    directory: Path, inherited: list[tuple[Path, GitIgnoreSpec]]
) -> list[tuple[Path, GitIgnoreSpec]]:
    path = directory / ".gitignore"
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return inherited
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_IGNORE_BYTES:
        raise LocalError(400, "source_file_rejected", "项目排除规则文件不可安全读取。")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            raw = os.read(descriptor, MAX_IGNORE_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(raw) > MAX_IGNORE_BYTES or b"\x00" in raw:
            raise ValueError("invalid gitignore")
        lines = raw.decode("utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise LocalError(400, "source_file_rejected", "项目排除规则文件不可安全读取。") from exc
    return [*inherited, (directory, GitIgnoreSpec.from_lines(lines))]


def is_ignored(path: Path, rules: list[tuple[Path, GitIgnoreSpec]], *, directory: bool) -> bool:
    ignored = False
    for base, spec in rules:
        relative = path.relative_to(base).as_posix() + ("/" if directory else "")
        match = spec.check_file(relative)
        if match.include is not None:
            ignored = match.include
    return ignored
