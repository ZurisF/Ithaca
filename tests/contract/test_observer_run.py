"""Observer must read real evidence and publish only a validated Markdown snapshot."""

from pathlib import Path
from uuid import uuid4

import pytest

from local_project.errors import LocalError
from local_project.observer.run import ObserverStep, observe


class ControlledObserver:
    def __init__(self, *, bad_citation: bool = False) -> None:
        self.calls = 0
        self.bad_citation = bad_citation

    async def generate_structured(self, **kwargs) -> ObserverStep:
        self.calls += 1
        if self.calls == 1:
            return ObserverStep(action="read_file_range", path="main.py", first_line=1, last_line=3)
        citation = "missing.py:L1-L3" if self.bad_citation else "main.py:L1-L3"
        return ObserverStep(
            action="finish",
            markdown=(
                "# Request Service\n## Modules\n### API\n入口与校验来自 "
                f"`{citation}`。\n## Threads\n### Request Flow\n"
                f"请求写入流程来自 `{citation}`。\n"
            ),
        )


@pytest.mark.asyncio
async def test_observer_reads_before_publishing_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("def handle(item):\n    return item\n", encoding="utf-8")
    model = ControlledObserver()
    markdown = await observe(root, uuid4(), model)
    assert "## Modules" in markdown and "## Threads" in markdown
    assert "`main.py:L1-L3`" in markdown
    assert model.calls == 2


@pytest.mark.asyncio
async def test_observer_rejects_citation_to_unread_file(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("def handle(): pass\n", encoding="utf-8")
    with pytest.raises(LocalError) as rejected:
        await observe(root, uuid4(), ControlledObserver(bad_citation=True))
    assert rejected.value.code == "observer_output_invalid"
