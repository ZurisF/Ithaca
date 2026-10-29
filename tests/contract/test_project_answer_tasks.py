"""Project-answer tasks carry the source handle in the request body (design 11.2)."""

from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from local_project.api.sources import get_observer_model
from local_project.main import app
from local_project.settings import get_settings


class FinishModel:
    """One bounded step that finishes without line-cited append evidence."""

    async def generate_structured(self, **kwargs):
        return kwargs["output_schema"](
            action="finish",
            post_verification_append="事后核验：README 说明请求使用混合检索与重排。",
            answers=[{"turn_no": 1, "project_answer": "项目使用检索与重排。"}],
        )


@pytest.mark.asyncio
async def test_project_answer_task_binds_body_handle_and_accepts_uncited_append(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("# 项目\n## Threads\n### Flow\n材料。\n", encoding="utf-8")
    session_id = uuid4()
    headers = {"Authorization": f"Bearer {get_settings().desktop_instance_token}"}
    model = FinishModel()
    app.dependency_overrides[get_observer_model] = lambda: model
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            authorized = await client.post(
                "/v1/sources:authorize",
                headers=headers,
                json={"session_id": str(session_id), "path": str(root)},
            )
            assert authorized.status_code == 200, authorized.text
            handle = authorized.json()["source_handle"]
            request = {
                "session_id": str(session_id),
                "operation_id": str(uuid4()),
                "source_handle": handle,
                "snapshot": "# 快照\n## Threads\n### Flow\n快照内容。\n",
                "turns": [{"turn_no": 1, "question": "检索链路？", "answer": "混合检索与重排。"}],
            }
            ok = await client.post("/v1/project-answer-tasks", headers=headers, json=request)
            assert ok.status_code == 200, ok.text
            body = ok.json()
            assert set(body) == {"post_verification_append", "answers"}
            assert body["answers"][0]["turn_no"] == 1

            stale = await client.post(
                "/v1/project-answer-tasks",
                headers=headers,
                json={**request, "session_id": str(uuid4()), "operation_id": str(uuid4())},
            )
            assert stale.status_code == 404, stale.text

            legacy = await client.post(
                f"/v1/sources/{handle}:project-answers", headers=headers, json=request
            )
            # No dedicated route anymore; only the generic /v1/sources/{handle}
            # collection matches this path, so a POST is rejected with 405.
            assert legacy.status_code == 405, legacy.text
    finally:
        app.dependency_overrides.pop(get_observer_model, None)
