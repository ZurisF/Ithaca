"""Observer tools never read outside the inventory or return raw secrets."""

import json
from pathlib import Path

import pytest

from local_project.errors import LocalError
from local_project.inventory.walk import inventory
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
