"""Fixed documented, code-only and oversized project coverage fixtures."""

from pathlib import Path
from uuid import uuid4

import pytest

from local_project.inventory.repository_map import build_repository_map
from local_project.inventory.walk import MAX_FILES, inventory
from local_project.observer.run import ObserverStep, observe

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/gate2"


class EvidenceObserver:
    def __init__(self, path: str, *, partial: bool = False) -> None:
        self.path = path
        self.partial = partial
        self.calls = 0

    async def generate_structured(self, **kwargs) -> ObserverStep:
        self.calls += 1
        assert self.path in kwargs["messages"][1].content
        if self.calls == 1:
            return ObserverStep(action="read_file_range", path=self.path, first_line=1, last_line=3)
        citation = f"`{self.path}:L1-L3`"
        return ObserverStep(
            action="finish",
            markdown=(
                f"# Project\n## Modules\n### Entry\n入口见 {citation}。\n"
                f"## Threads\n### Main flow\n流程见 {citation}。\n"
                + ("部分分析；未覆盖其余文件。\n" if self.partial else "")
            ),
        )


@pytest.mark.parametrize(
    ("fixture", "entry"),
    [("documented", "README.md"), ("code_only", "main.py")],
)
@pytest.mark.asyncio
async def test_documented_and_code_only_projects_have_evidence(fixture: str, entry: str) -> None:
    root = FIXTURES / fixture
    items, partial = inventory(root)
    assert not partial
    files = {item.relative_path for item in items if item.kind == "file"}
    assert entry in files
    if fixture == "code_only":
        assert not any(path.lower().startswith("readme") for path in files)
    repository_map = build_repository_map(root, items)
    assert entry in repository_map.text
    assert "Python" in repository_map.text
    model = EvidenceObserver(entry)
    snapshot = await observe(root, uuid4(), model)
    assert model.calls == 2
    assert f"`{entry}:L1-L3`" in snapshot


@pytest.mark.asyncio
async def test_oversized_project_is_explicitly_partial(tmp_path: Path) -> None:
    root = tmp_path / "oversized"
    root.mkdir()
    (root / "00_main.py").write_text("def main():\n    return 1\n# entry\n", encoding="utf-8")
    for index in range(MAX_FILES + 10):
        (root / f"file_{index:04d}.py").write_text("def helper(): pass\n", encoding="utf-8")
    items, inventory_partial = inventory(root)
    assert inventory_partial
    assert len(items) == MAX_FILES
    repository_map = build_repository_map(root, items, inventory_partial=inventory_partial)
    assert repository_map.partial
    snapshot = await observe(root, uuid4(), EvidenceObserver("00_main.py", partial=True))
    assert "部分分析" in snapshot and "未覆盖" in snapshot
