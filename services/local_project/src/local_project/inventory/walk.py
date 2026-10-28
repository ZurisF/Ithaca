"""Deterministic bounded inventory; discovery never grants subsequent read access."""

import os
from dataclasses import dataclass
from pathlib import Path

from content_safety import SafetyHit
from local_project.inventory.ignore import is_ignored, load_rules
from local_project.settings import get_settings
from local_project.tools.read_only import (
    HARD_EXCLUDED,
    is_sensitive_path,
    read_file_safety,
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
    redactions: tuple[SafetyHit, ...] = ()


def inventory(root: Path) -> tuple[list[InventoryItem], bool]:
    settings = get_settings()
    max_items = settings.inventory_max_items
    items: list[InventoryItem] = []
    partial = False
    visited_directories = 0
    rules_by_directory = {root: load_rules(root, [])}
    for directory, subdirs, files in os.walk(root, topdown=True, followlinks=False):
        visited_directories += 1
        if visited_directories > max_items:
            return items, True
        current = Path(directory)
        rules = rules_by_directory[current]
        included_directories = []
        for name in sorted(subdirs):
            if len(items) >= max_items:
                return items, True
            path = current / name
            relative = path.relative_to(root).as_posix()
            if name.casefold() in HARD_EXCLUDED or name.casefold().startswith(".git"):
                items.append(InventoryItem(relative, "directory", None, None, "sensitive_name"))
            elif path.is_symlink():
                items.append(InventoryItem(relative, "symlink", None, None, "symlink"))
            elif any(os.path.lexists(path / marker) for marker in (".git", ".hg", ".svn")):
                items.append(InventoryItem(relative, "directory", None, None, "nested_repository"))
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
            if len(items) >= max_items:
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
                if size > settings.max_file_bytes:
                    items.append(InventoryItem(relative, "file", size, None, "too_large"))
                    continue
                # Open through the same no-follow path as real tool reads; inventory does not cache content.
                safe = read_file_safety(root, relative)
            except Exception:  # noqa: BLE001 - a file can disappear or become unreadable mid-walk
                items.append(InventoryItem(relative, "file", None, None, "unreadable_or_binary"))
                continue
            items.append(InventoryItem(relative, "file", size, "utf-8", None, safe.hits))
    return items, partial
