"""Read-only observer tools over a single inventory allowlist."""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from local_project.errors import LocalError
from local_project.inventory.repository_map import file_symbols
from local_project.inventory.walk import InventoryItem
from local_project.settings import get_settings
from local_project.tools.read_only import read_file_range, read_file_text


def _encode(payload: dict) -> tuple[str, bool]:
    max_chars = get_settings().observer_tool_chars
    body = json.dumps(payload, ensure_ascii=False)
    if len(body) <= max_chars:
        return body, False
    return json.dumps(
        {"truncated": True, "preview": body[: max_chars // 4]}, ensure_ascii=False
    ), True


@dataclass(frozen=True)
class ToolResult:
    text: str
    read_paths: frozenset[str]
    evidence_lines: dict[str, frozenset[int]]
    truncated: bool


class ProjectTools:
    def __init__(self, root: Path, inventory_items: list[InventoryItem]) -> None:
        self.root = root
        self.items = inventory_items
        self.allowed = {
            item.relative_path
            for item in inventory_items
            if item.kind == "file" and item.skip_reason is None
        }

    def _safe_path(self, value: str | None, *, exact: bool) -> str:
        if not value:
            if exact:
                raise LocalError(400, "invalid_request", "需要选择清点结果中的文件。")
            return ""
        parsed = PurePosixPath(value)
        if parsed.is_absolute() or ".." in parsed.parts or not parsed.parts:
            raise LocalError(400, "invalid_request", "工具路径必须位于授权目录内。")
        path = parsed.as_posix()
        if exact and path not in self.allowed:
            raise LocalError(400, "source_file_rejected", "文件不在本次安全清单中。")
        return path

    def list_tree(self, subtree: str | None = None) -> ToolResult:
        limit = get_settings().observer_search_files
        prefix = self._safe_path(subtree, exact=False)
        entries = [
            {"path": item.relative_path, "kind": item.kind, "skip_reason": item.skip_reason}
            for item in self.items
            if not prefix
            or item.relative_path == prefix
            or item.relative_path.startswith(prefix + "/")
        ]
        body, clipped = _encode({"entries": entries[:limit], "truncated": len(entries) > limit})
        return ToolResult(body, frozenset(), {}, clipped or len(entries) > limit)

    def read_range(
        self, path: str | None, first_line: int | None, last_line: int | None
    ) -> ToolResult:
        chosen = self._safe_path(path, exact=True)
        if first_line is None or last_line is None:
            raise LocalError(400, "invalid_request", "读取文件时需要行号范围。")
        content = read_file_range(self.root, chosen, first_line, last_line)
        body, clipped = _encode(
            {"path": chosen, "first_line": first_line, "last_line": last_line, "content": content},
        )
        visible_lines = content.count("\n") + 1 if content else 0
        evidence = (
            {chosen: frozenset(range(first_line, first_line + visible_lines))}
            if visible_lines and not clipped
            else {}
        )
        return ToolResult(body, frozenset({chosen}), evidence, clipped)

    def get_symbols(self, path: str | None) -> ToolResult:
        chosen = self._safe_path(path, exact=True)
        content = read_file_text(self.root, chosen)
        symbols = [asdict(item) for item in file_symbols(chosen, content)]
        body, clipped = _encode({"path": chosen, "symbols": symbols})
        evidence = (
            {chosen: frozenset(symbol["line"] for symbol in symbols)}
            if symbols and not clipped
            else {}
        )
        return ToolResult(body, frozenset({chosen}), evidence, clipped)

    def search(self, query: str | None, path_filter: str | None, *, whole_word: bool) -> ToolResult:
        settings = get_settings()
        if not query or len(query) > 100 or any(ord(char) < 32 for char in query):
            raise LocalError(400, "invalid_request", "检索词无效。")
        prefix = self._safe_path(path_filter, exact=False)
        candidates = sorted(
            path
            for path in self.allowed
            if not prefix or path == prefix or path.startswith(prefix + "/")
        )
        pattern = re.compile(
            rf"\b{re.escape(query)}\b" if whole_word else re.escape(query), re.IGNORECASE
        )
        matches = []
        read_paths = set()
        for path in candidates[: settings.observer_search_files]:
            try:
                lines = read_file_text(self.root, path).splitlines()
            except LocalError:
                continue
            for line_no, line in enumerate(lines, 1):
                if pattern.search(line):
                    matches.append({"path": path, "line": line_no, "excerpt": line[:200]})
                    read_paths.add(path)
                    if len(matches) >= settings.observer_search_matches:
                        break
            if len(matches) >= settings.observer_search_matches:
                break
        truncated = (
            len(candidates) > settings.observer_search_files
            or len(matches) >= settings.observer_search_matches
        )
        body, clipped = _encode({"matches": matches, "truncated": truncated})
        evidence: dict[str, set[int]] = {}
        if not clipped:
            for match in matches:
                evidence.setdefault(match["path"], set()).add(match["line"])
        return ToolResult(
            body,
            frozenset(read_paths),
            {path: frozenset(lines) for path, lines in evidence.items()},
            truncated or clipped,
        )

    def execute(
        self,
        action: str,
        *,
        path: str | None = None,
        query: str | None = None,
        first_line: int | None = None,
        last_line: int | None = None,
    ) -> ToolResult:
        if action == "list_tree":
            return self.list_tree(path)
        if action == "search_text":
            return self.search(query, path, whole_word=False)
        if action == "get_file_symbols":
            return self.get_symbols(path)
        if action == "find_symbol_references":
            return self.search(query, path, whole_word=True)
        if action == "read_file_range":
            return self.read_range(path, first_line, last_line)
        raise LocalError(400, "invalid_request", "未知只读工具。")
