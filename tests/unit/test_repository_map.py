"""Repository Map fixtures cover docs, code, and bounded partial analysis."""

from pathlib import Path

from local_project.inventory.repository_map import build_repository_map
from local_project.inventory.walk import inventory


def _map(root: Path, *, max_files: int = 120, max_chars: int = 20_000):
    items, partial = inventory(root)
    return build_repository_map(
        root, items, max_files=max_files, max_chars=max_chars, inventory_partial=partial
    )


def test_documented_project_map_marks_readme_and_framework(tmp_path: Path) -> None:
    root = tmp_path / "documented"
    root.mkdir()
    (root / "README.md").write_text("# Service\nA documented API.\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\ndependencies = ["fastapi"]\n', encoding="utf-8"
    )
    result = _map(root)
    assert "README.md" in result.text
    assert "FastAPI" in result.text
    assert not result.partial


def test_code_only_project_map_uses_ast_signatures_without_values(tmp_path: Path) -> None:
    root = tmp_path / "code"
    root.mkdir()
    (root / "main.py").write_text(
        "class Store:\n    def save(self, item):\n        return item\n\n"
        "def start(port):\n    return Store()\n",
        encoding="utf-8",
    )
    result = _map(root)
    assert "class Store:L1" in result.text
    assert "Store.save(self, item):L2" in result.text
    assert "start(port):L5" in result.text


def test_large_project_map_reports_omitted_files_and_never_emits_secret(
    tmp_path: Path,
) -> None:
    root = tmp_path / "large"
    root.mkdir()
    for index in range(12):
        (root / f"module_{index}.py").write_text(
            f"api_key = 'sk-123456789012345678901234'\ndef feature_{index}():\n    pass\n",
            encoding="utf-8",
        )
    result = _map(root, max_files=3, max_chars=2_000)
    assert result.partial
    assert result.omitted_files == 9
    assert len(result.included_paths) == 3
    assert "sk-123456789012345678901234" not in result.text
    assert "partial=true" in result.text
