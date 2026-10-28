"""Local Runtime authorization and file-open security boundaries."""

import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from local_project.errors import LocalError
from local_project.inventory.walk import inventory
from local_project.main import app
from local_project.settings import get_settings
from local_project.tools.read_only import read_file_range


@pytest.mark.asyncio
async def test_handle_is_bound_to_one_session_and_exposes_no_absolute_path(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("# 项目\n可读材料。\n", encoding="utf-8")
    (root / ".env").write_text("SECRET_CANARY=never_return_this", encoding="utf-8")
    (root / "config.py").write_text(
        "# sample\napi_key = 'sk-123456789012345678901234'\n", encoding="utf-8"
    )
    session_id = uuid4()
    other_session = uuid4()
    headers = {"Authorization": f"Bearer {get_settings().desktop_instance_token}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        unauthorized = await client.post(
            "/v1/sources:authorize", json={"session_id": str(session_id), "path": str(root)}
        )
        assert unauthorized.status_code == 401
        authorized = await client.post(
            "/v1/sources:authorize",
            headers=headers,
            json={"session_id": str(session_id), "path": str(root)},
        )
        assert authorized.status_code == 200, authorized.text
        handle = authorized.json()["source_handle"]
        assert str(root) not in authorized.text
        inventory_url = f"/v1/sources/{handle}/inventory"
        allowed = await client.get(
            inventory_url, headers=headers, params={"session_id": str(session_id)}
        )
        assert allowed.status_code == 200, allowed.text
        assert str(root) not in allowed.text
        assert "SECRET_CANARY" not in allowed.text
        assert "sk-123456789012345678901234" not in allowed.text
        assert any(item["relative_path"] == "README.md" for item in allowed.json()["files"])
        config = next(
            item for item in allowed.json()["files"] if item["relative_path"] == "config.py"
        )
        assert config["redactions"] == [{"kind": "credential_assignment", "line": 2}]
        assert (
            await client.get(
                inventory_url, headers=headers, params={"session_id": str(other_session)}
            )
        ).status_code == 404
        released = await client.delete(
            f"/v1/sources/{handle}", headers=headers, params={"session_id": str(session_id)}
        )
        assert released.status_code == 200
        assert (
            await client.get(inventory_url, headers=headers, params={"session_id": str(session_id)})
        ).status_code == 404


def test_symlink_replacement_after_inventory_cannot_escape_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    source = root / "safe.md"
    source.write_text("safe content\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("OUTSIDE_CANARY\n", encoding="utf-8")
    assert read_file_range(root, "safe.md", 1, 1) == "safe content"
    os.replace(source, root / "old-safe.md")
    source.symlink_to(outside)
    with pytest.raises(LocalError) as rejected:
        read_file_range(root, "safe.md", 1, 1)
    assert rejected.value.code == "source_file_rejected"
    assert "OUTSIDE_CANARY" not in rejected.value.message


def test_sensitive_paths_cannot_be_read_directly(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / ".env").write_text("SECRET_CANARY=hidden\n", encoding="utf-8")
    (root / ".ENV.local").write_text("SECRET_CANARY=hidden\n", encoding="utf-8")
    private_dir = root / "src" / ".aws"
    private_dir.mkdir(parents=True)
    (private_dir / "credentials.ini").write_text("SECRET_CANARY=hidden\n", encoding="utf-8")
    for relative in (".env", ".ENV.local", "src/.aws/credentials.ini"):
        with pytest.raises(LocalError) as rejected:
            read_file_range(root, relative, 1, 1)
        assert rejected.value.code == "source_file_rejected"
        assert "SECRET_CANARY" not in rejected.value.message


def test_inventory_applies_nested_gitignore_but_cannot_override_hard_excludes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / ".gitignore").write_text("*.log\n*.md\n!keep.md\n!.env\n", encoding="utf-8")
    (root / "debug.log").write_text("debug\n", encoding="utf-8")
    (root / "hidden.md").write_text("hidden\n", encoding="utf-8")
    (root / "keep.md").write_text("kept\n", encoding="utf-8")
    (root / ".env").write_text("SECRET_CANARY=hidden\n", encoding="utf-8")
    nested = root / "src"
    nested.mkdir()
    (nested / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    (nested / "scratch.tmp").write_text("temporary\n", encoding="utf-8")
    (nested / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    items, partial = inventory(root)
    assert not partial
    reasons = {item.relative_path: item.skip_reason for item in items}
    assert reasons["debug.log"] == "gitignored"
    assert reasons["hidden.md"] == "gitignored"
    assert reasons["keep.md"] is None
    assert reasons[".env"] == "sensitive_name"
    assert reasons["src/scratch.tmp"] == "gitignored"
    assert reasons["src/main.py"] is None


def test_inventory_skips_nested_repository_and_submodule(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    nested = root / "nested"
    nested.mkdir()
    (nested / ".git").mkdir()
    (nested / "private.py").write_text("CANARY_NESTED_REPO\n", encoding="utf-8")
    submodule = root / "submodule"
    submodule.mkdir()
    (submodule / ".git").write_text("gitdir: ../.git/modules/submodule\n", encoding="utf-8")
    (submodule / "private.py").write_text("CANARY_SUBMODULE\n", encoding="utf-8")

    items, partial = inventory(root)
    assert not partial
    reasons = {item.relative_path: item.skip_reason for item in items}
    assert reasons["main.py"] is None
    assert reasons["nested"] == "nested_repository"
    assert reasons["submodule"] == "nested_repository"
    assert "nested/private.py" not in reasons
    assert "submodule/private.py" not in reasons
