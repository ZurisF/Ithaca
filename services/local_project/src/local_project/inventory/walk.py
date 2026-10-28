"""Deterministic bounded inventory; discovery never grants subsequent read access."""

import os
from dataclasses import dataclass
from pathlib import Path

from local_project.inventory.ignore import is_ignored, load_rules
from local_project.tools.read_only import (
    HARD_EXCLUDED,
    MAX_FILE_BYTES,
    is_sensitive_path,
    read_file_range,
)

ALLOWED_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sh",
    ".sql",
    ".html",
    ".css",
    ".xml",
    ".csv",
    ".ini",
    ".cfg",
}
MAX_FILES = 2_000


@dataclass(frozen=True)
class InventoryItem:
    relative_path: str
    kind: str
    size: int | None
    encoding: str | None
    skip_reason: str | None


def inventory(root: Path) -> tuple[list[InventoryItem], bool]:
    items: list[InventoryItem] = []
    partial = False
    visited_directories = 0
    rules_by_directory = {root: load_rules(root, [])}
    for directory, subdirs, files in os.walk(root, topdown=True, followlinks=False):
        visited_directories += 1
        if visited_directories > MAX_FILES:
            return items, True
        current = Path(directory)
        rules = rules_by_directory[current]
        included_directories = []
        for name in sorted(subdirs):
            if len(items) >= MAX_FILES:
                return items, True
            path = current / name
            relative = path.relative_to(root).as_posix()
            if name.casefold() in HARD_EXCLUDED or name.casefold().startswith(".git"):
                items.append(InventoryItem(relative, "directory", None, None, "sensitive_name"))
            elif path.is_symlink():
                items.append(InventoryItem(relative, "symlink", None, None, "symlink"))
            elif is_ignored(path, rules, directory=True):
                items.append(InventoryItem(relative, "directory", None, None, "gitignored"))
            else:
                try:
                    rules_by_directory[path] = load_rules(path, rules)
                except Exception:  # noqa: BLE001 - unreadable rules must not expose a subtree
                    items.append(
                        InventoryItem(relative, "directory", None, None, "unreadable_rules")
                    )
                    partial = True
                    continue
                included_directories.append(name)
        subdirs[:] = included_directories
        for name in sorted(files):
            if len(items) >= MAX_FILES:
                partial = True
                return items, partial
            path = current / name
            relative = path.relative_to(root).as_posix()
            if is_sensitive_path(tuple(Path(relative).parts)):
                items.append(InventoryItem(relative, "file", None, None, "sensitive_name"))
                continue
            if is_ignored(path, rules, directory=False):
                items.append(InventoryItem(relative, "file", None, None, "gitignored"))
                continue
            if path.is_symlink():
                items.append(InventoryItem(relative, "symlink", None, None, "symlink"))
                continue
            if path.suffix.lower() not in ALLOWED_SUFFIXES and name not in {
                "Dockerfile",
                "Makefile",
                ".gitignore",
            }:
                items.append(InventoryItem(relative, "file", None, None, "unsupported_type"))
                continue
            try:
                size = path.stat().st_size
                if size > MAX_FILE_BYTES:
                    items.append(InventoryItem(relative, "file", size, None, "too_large"))
                    continue
                # Open through the same no-follow path as real tool reads; inventory does not cache content.
                read_file_range(root, relative, 1, 1)
            except Exception:  # noqa: BLE001 - a file can disappear or become unreadable mid-walk
                items.append(InventoryItem(relative, "file", None, None, "unreadable_or_binary"))
                continue
            items.append(InventoryItem(relative, "file", size, "utf-8", None))
    return items, partial
