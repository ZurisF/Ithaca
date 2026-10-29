"""Iterative evidence collection and bounded snapshot publication in Local Runtime."""

import json
import re
import time
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from content_safety import ContentRejected, filter_text, snapshot_headings, visible_snapshot_lines
from local_project.errors import LocalError
from local_project.inventory.repository_map import build_repository_map
from local_project.inventory.walk import inventory
from local_project.settings import get_settings
from local_project.tools.project import ProjectTools
from model_adapter import Message, ModelAdapter, ModelFailure, RetryPolicy

PROMPT = Path(__file__).resolve().parents[5] / "packages/prompt_assets/prompts/observer/v1.md"
CITATION = re.compile(r"`([^`\n]+):L(\d+)(?:-L(\d+))?`")


class ObserverStep(BaseModel):
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
    markdown: str | None = Field(default=None, max_length=20_000)


def _model_input_bytes(messages: list[Message]) -> int:
    """Conservative token upper bound for byte-based chat model tokenizers."""
    payload = json.dumps([message.__dict__ for message in messages], ensure_ascii=False)
    schema = json.dumps(ObserverStep.model_json_schema(), ensure_ascii=False)
    return len(payload.encode("utf-8")) + len(schema.encode("utf-8")) + 500


def _validate_snapshot(
    markdown: str, evidence_lines: dict[str, set[int]], *, partial: bool
) -> list[str]:
    errors = []
    try:
        safety = filter_text(markdown, max_chars=200_000)
        if safety.changed:
            errors.append("snapshot contains a sensitive value")
    except ContentRejected:
        return ["snapshot content is empty, unsafe or over budget"]
    current_kind = None
    sections: list[tuple[str, str, str]] = []
    lines = visible_snapshot_lines(markdown)
    seen = set()
    headings = set()
    structure = snapshot_headings(markdown)
    for index, heading in enumerate(structure):
        if heading.level == 2:
            if heading.title in {"Modules", "Threads"}:
                headings.add(heading.title)
            current_kind = {"Modules": "module", "Threads": "thread"}.get(heading.title)
        elif current_kind:
            title = heading.title
            key = (current_kind, title)
            if not title or key in seen:
                errors.append("empty or duplicate Module/Thread heading")
            seen.add(key)
            end = structure[index + 1].line_index if index + 1 < len(structure) else len(lines)
            sections.append((current_kind, title, "\n".join(lines[heading.line_index + 1 : end])))
    if headings != {"Modules", "Threads"}:
        errors.append("snapshot needs both Modules and Threads headings")
    if not sections:
        errors.append("snapshot needs at least one evidence-backed Module or Thread")
    visible = "\n".join(lines)
    citations = list(CITATION.finditer(visible))
    if re.search(r":L\d+", CITATION.sub("", visible)):
        errors.append("file and line citations must be wrapped in backticks")
    for match in citations:
        path = match.group(1)
        first = int(match.group(2))
        last = int(match.group(3) or first)
        if (
            last < first
            or last - first > 200
            or not set(range(first, last + 1)) <= evidence_lines.get(path, set())
        ):
            errors.append("snapshot cites file lines not visible in an authorized tool result")
    for kind, title, body in sections:
        if not any(CITATION.finditer(body)):
            errors.append(f"{kind} {title} needs a file and line citation")
    if partial and ("部分分析" not in markdown or "未覆盖" not in markdown):
        errors.append("partial coverage must disclose 部分分析 and 未覆盖 scope")
    return errors


async def observe(root: Path, session_id: UUID, model: ModelAdapter) -> str:
    settings = get_settings()
    items, inventory_partial = inventory(root)
    tools = ProjectTools(root, items)
    if not tools.allowed:
        raise LocalError(422, "source_file_rejected", "目录中没有可安全读取的材料。")
    map_result = build_repository_map(
        root,
        items,
        max_files=settings.observer_map_files,
        max_chars=settings.observer_map_chars,
        inventory_partial=inventory_partial,
    )
    messages = [
        Message(role="system", content=PROMPT.read_text(encoding="utf-8")),
        Message(
            role="user",
            content=json.dumps(
                {
                    "repository_map": map_result.text,
                    "eligible_file_count": len(tools.allowed),
                    "inventory_partial": inventory_partial,
                    "map_partial": map_result.partial,
                },
                ensure_ascii=False,
            ),
        ),
    ]
    evidence_lines: dict[str, set[int]] = {}
    seen_calls: set[str] = set()
    partial = map_result.partial
    total_chars = len(map_result.text)
    deadline = time.monotonic() + settings.observer_timeout_seconds
    tool_steps = 0
    model_token_upper = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 5:
            raise LocalError(503, "observer_timeout", "目录观察已超过总耗时预算。")
        if remaining <= 20 and not evidence_lines:
            raise LocalError(503, "observer_timeout", "目录观察未能在耗时预算内取得文件证据。")
        time_needs_finish = bool(evidence_lines) and remaining <= 25
        current_input = _model_input_bytes(messages)
        current_call_upper = 2 * (current_input + settings.observer_step_max_tokens)
        budget_needs_finish = bool(evidence_lines) and (
            model_token_upper + 2 * current_call_upper >= settings.observer_total_model_tokens
        )
        must_finish = (
            tool_steps >= settings.observer_tool_steps
            or total_chars >= settings.observer_total_chars
            or budget_needs_finish
            or time_needs_finish
        )
        if must_finish:
            partial = True
            messages.append(
                Message(
                    role="user",
                    content="工具预算已到。下一步必须 finish，明确写部分分析与未覆盖范围。",
                )
            )
        input_bytes = _model_input_bytes(messages)
        call_upper = 2 * (input_bytes + settings.observer_step_max_tokens)
        if (
            input_bytes > settings.observer_max_prompt_bytes
            or model_token_upper + call_upper > settings.observer_total_model_tokens
        ):
            raise LocalError(503, "observer_budget_exhausted", "项目观察已达到模型预算。")
        model_token_upper += call_upper

        def validate(
            step: ObserverStep, current_partial: bool = partial, finish_only: bool = must_finish
        ) -> list[str]:
            if step.action == "finish":
                if step.markdown is None or not evidence_lines:
                    return ["finish requires markdown and at least one actual file read"]
                return _validate_snapshot(step.markdown, evidence_lines, partial=current_partial)
            if finish_only:
                return ["tool budget reached; action must be finish"]
            if step.markdown is not None:
                return ["tool action cannot include markdown"]
            return []

        try:
            step = await model.generate_structured(
                session_id=session_id,
                operation="observer_step",
                messages=messages,
                output_schema=ObserverStep,
                prompt_version="observer-v1",
                retry_policy=RetryPolicy(
                    max_attempts=2,
                    deadline_seconds=min(45, remaining - (2 if must_finish else 20)),
                ),
                validate_output=validate,
                max_completion_tokens=settings.observer_step_max_tokens,
            )
        except ModelFailure as exc:
            if exc.code == "dependency_unavailable":
                raise LocalError(503, "dependency_unavailable", "模型尚未配置。") from exc
            raise LocalError(503, "observer_model_failed", "项目观察模型调用失败。") from exc
        # Controlled adapters must pass the same deterministic barrier as production.
        if validate(step):
            raise LocalError(422, "observer_output_invalid", "项目观察结果未通过证据校验。")
        if step.action == "finish":
            assert step.markdown is not None
            return filter_text(step.markdown).text

        call_key = json.dumps(step.model_dump(exclude={"markdown"}), sort_keys=True)
        if call_key in seen_calls:
            partial = True
            tool_steps = settings.observer_tool_steps
            messages.append(
                Message(role="user", content="重复工具请求没有新增证据。请结束并标记部分分析。")
            )
            continue
        seen_calls.add(call_key)
        tool_steps += 1
        try:
            result = tools.execute(
                step.action,
                path=step.path,
                query=step.query,
                first_line=step.first_line,
                last_line=step.last_line,
            )
            next_messages = [
                *messages,
                Message(role="assistant", content=step.model_dump_json()),
                Message(role="user", content=f"Tool result for {step.action}: {result.text}"),
            ]
            if (
                total_chars + len(result.text) > settings.observer_total_chars
                or _model_input_bytes(next_messages) > settings.observer_max_prompt_bytes
            ):
                partial = True
                tool_steps = settings.observer_tool_steps
                tool_text = '{"truncated":true,"reason":"observer text or context budget"}'
            else:
                tool_text = result.text
                total_chars += len(tool_text)
                for path, lines in result.evidence_lines.items():
                    evidence_lines.setdefault(path, set()).update(lines)
                partial = partial or result.truncated
        except LocalError as exc:
            tool_text = json.dumps({"error_code": exc.code}, ensure_ascii=False)
        messages.extend(
            [
                Message(role="assistant", content=step.model_dump_json()),
                Message(role="user", content=f"Tool result for {step.action}: {tool_text}"),
            ]
        )
