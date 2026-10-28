"""Observer must read real evidence and publish only a validated Markdown snapshot."""

from pathlib import Path
from uuid import uuid4

import pytest

from local_project.errors import LocalError
from local_project.observer.run import ObserverStep, observe
from local_project.settings import get_settings


class ControlledObserver:
    def __init__(
        self, *, bad_citation: bool = False, bad_line: bool = False, partial: bool = False
    ) -> None:
        self.calls = 0
        self.bad_citation = bad_citation
        self.bad_line = bad_line
        self.partial = partial

    async def generate_structured(self, **kwargs) -> ObserverStep:
        self.calls += 1
        if self.calls == 1:
            return ObserverStep(action="read_file_range", path="main.py", first_line=1, last_line=3)
        citation = "missing.py:L1-L2" if self.bad_citation else "main.py:L1-L2"
        if self.bad_line:
            citation = "main.py:L99"
        return ObserverStep(
            action="finish",
            markdown=(
                "# Request Service\n## Modules\n### API\n入口与校验来自 "
                f"`{citation}`。\n## Threads\n### Request Flow\n"
                f"请求写入流程来自 `{citation}`。\n"
                + ("\n部分分析；未覆盖其余文件。\n" if self.partial else "")
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
    assert "`main.py:L1-L2`" in markdown
    assert model.calls == 2


@pytest.mark.asyncio
async def test_observer_rejects_citation_to_unread_file(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("def handle(): pass\n", encoding="utf-8")
    with pytest.raises(LocalError) as rejected:
        await observe(root, uuid4(), ControlledObserver(bad_citation=True))
    assert rejected.value.code == "observer_output_invalid"


@pytest.mark.asyncio
async def test_observer_rejects_citation_to_unseen_line(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("def handle(): pass\n", encoding="utf-8")
    with pytest.raises(LocalError) as rejected:
        await observe(root, uuid4(), ControlledObserver(bad_line=True))
    assert rejected.value.code == "observer_output_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize("disclose_partial", [False, True])
async def test_map_budget_requires_explicit_partial_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, disclose_partial: bool
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("def handle(item):\n    return item\n", encoding="utf-8")
    for index in range(20):
        (root / f"module_{index:02d}.py").write_text(
            f"def feature_{index}():\n    return {index}\n", encoding="utf-8"
        )
    monkeypatch.setattr(get_settings(), "observer_map_files", 1)
    model = ControlledObserver(partial=disclose_partial)
    if disclose_partial:
        snapshot = await observe(root, uuid4(), model)
        assert "部分分析" in snapshot and "未覆盖" in snapshot
    else:
        with pytest.raises(LocalError) as rejected:
            await observe(root, uuid4(), model)
        assert rejected.value.code == "observer_output_invalid"
