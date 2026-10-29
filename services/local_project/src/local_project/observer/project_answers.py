"""Bounded, read-only project answer investigation in the authorized source."""

import json
import re
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from content_safety import ContentRejected, filter_text
from local_project.errors import LocalError
from local_project.inventory.repository_map import build_repository_map
from local_project.inventory.walk import inventory
from local_project.tools.project import ProjectTools
from model_adapter import Message, ModelAdapter, RetryPolicy

PROMPT = (
    Path(__file__).resolve().parents[5] / "packages/prompt_assets/prompts/post/project_local_v1.md"
)


class ProjectAnswerStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "list_tree",
        "search_text",
        "get_file_symbols",
        "find_symbol_references",
        "read_file_range",
        "finish",
    ]
    path: str | None = Field(default=None, max_length=4_096)
    query: str | None = Field(default=None, max_length=100)
    first_line: int | None = Field(default=None, ge=1)
    last_line: int | None = Field(default=None, ge=1)
    post_verification_append: str | None = Field(default=None, max_length=4_000)
    answers: list[dict] | None = Field(default=None, max_length=100)


async def project_answers(
    root: Path,
    session_id: UUID,
    snapshot: str,
    turns: list[dict],
    model: ModelAdapter,
) -> dict:
    try:
        snapshot = filter_text(snapshot, max_chars=200_000).text
        turns = [
            {
                "turn_no": turn["turn_no"],
                "question": filter_text(turn["question"], max_chars=1_000).text,
                "answer": filter_text(turn["answer"], max_chars=8_000).text,
            }
            for turn in turns
        ]
    except ContentRejected as exc:
        raise LocalError(422, "source_file_rejected", "赛后材料未通过安全检查。") from exc
    items, partial = inventory(root)
    tools = ProjectTools(root, items)
    repo_map = build_repository_map(root, items)
    history: list[dict] = []
    evidence: dict[str, set[int]] = {}
    for step_no in range(6):
        payload = {
            "snapshot": snapshot,
            "turns": turns,
            "repository_map": repo_map.text,
            "inventory_partial": partial,
            "tool_history": history[-5:],
            "remaining_tool_steps": 5 - step_no,
        }
        step = await model.generate_structured(
            session_id=session_id,
            operation="project_answers_local",
            messages=[
                Message(role="system", content=PROMPT.read_text(encoding="utf-8")),
                Message(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ],
            output_schema=ProjectAnswerStep,
            prompt_version="v1",
            retry_policy=RetryPolicy(max_attempts=3, deadline_seconds=180),
        )
        if step.action == "finish":
            if step.answers is None:
                raise ValueError("project answers missing")
            if step.post_verification_append:
                citations = re.findall(
                    r"`([^`\n]+):L(\d+)(?:-L(\d+))?`", step.post_verification_append
                )
                if not citations:
                    raise ValueError("post verification needs read evidence")
                for path, first, last in citations:
                    needed = range(int(first), int(last or first) + 1)
                    if any(line not in evidence.get(path, set()) for line in needed):
                        raise ValueError("post verification cites unread evidence")
            return {
                "post_verification_append": step.post_verification_append,
                "answers": step.answers,
            }
        result = tools.execute(
            step.action,
            path=step.path,
            query=step.query,
            first_line=step.first_line,
            last_line=step.last_line,
        )
        for path, lines in result.evidence_lines.items():
            evidence.setdefault(path, set()).update(lines)
        history.append({"action": step.action, "result": result.text})
    raise ValueError("project answer tool budget exhausted")
