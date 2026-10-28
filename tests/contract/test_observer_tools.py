"""Observer tools never read outside the inventory or return raw secrets."""

import json
from pathlib import Path

import pytest

from local_project.errors import LocalError
from local_project.inventory.walk import inventory
from local_project.settings import get_settings
from local_project.tools.project import ProjectTools


def test_tools_respect_inventory_and_redact_search_results(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / ".gitignore").write_text("private.md\n", encoding="utf-8")
    (root / "main.py").write_text(
        "def handle(item):\n    api_key = 'sk-123456789012345678901234'\n    return item\n",
        encoding="utf-8",
    )
    (root / "private.md").write_text("PRIVATE_CANARY\n", encoding="utf-8")
    (root / ".env").write_text("SECRET_CANARY=hidden\n", encoding="utf-8")
    items, _ = inventory(root)
    tools = ProjectTools(root, items)
    assert "main.py" in tools.allowed
    assert "private.md" not in tools.allowed
    assert ".env" not in tools.allowed
    read = tools.execute("read_file_range", path="main.py", first_line=1, last_line=3)
    assert "sk-123456789012345678901234" not in read.text
    assert "[已脱敏]" in read.text
    assert read.read_paths == {"main.py"}
    symbols = tools.execute("get_file_symbols", path="main.py")
    assert "handle" in symbols.text
    matches = tools.execute("search_text", query="return", path="main.py")
    assert json.loads(matches.text)["matches"][0]["path"] == "main.py"
    for path in ("private.md", ".env", "../outside.md"):
        with pytest.raises(LocalError):
            tools.execute("read_file_range", path=path, first_line=1, last_line=1)


def test_configured_file_and_inventory_budgets_are_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.py").write_text("def a(): pass\n", encoding="utf-8")
    (root / "b.py").write_text("def b(): pass\n", encoding="utf-8")
    (root / "huge.py").write_text("x" * 2_000, encoding="utf-8")
    settings = get_settings()
    monkeypatch.setattr(settings, "max_file_bytes", 1_024)
    items, partial = inventory(root)
    assert not partial
    assert {item.relative_path: item.skip_reason for item in items}["huge.py"] == "too_large"
    monkeypatch.setattr(settings, "inventory_max_items", 2)
    items, partial = inventory(root)
    assert partial
    assert len(items) == 2


def test_configured_search_and_tool_text_budgets_are_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.py").write_text("needle\n" + "x" * 1_000, encoding="utf-8")
    (root / "b.py").write_text("needle\n", encoding="utf-8")
    tools = ProjectTools(root, inventory(root)[0])
    settings = get_settings()
    monkeypatch.setattr(settings, "observer_search_files", 1)
    monkeypatch.setattr(settings, "observer_tool_chars", 500)
    searched = tools.execute("search_text", query="needle")
    assert searched.truncated
    assert len(json.loads(searched.text)["matches"]) == 1
    read = tools.execute("read_file_range", path="a.py", first_line=1, last_line=2)
    assert read.truncated
    assert len(read.text) <= 500
    assert read.evidence_lines == {}
