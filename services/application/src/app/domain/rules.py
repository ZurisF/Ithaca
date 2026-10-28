"""Deterministic rules shared by command paths and tests."""

import re
from collections.abc import Iterable
from uuid import UUID

from app.domain.contracts import InterviewPlan, SectionRef

HEADING = re.compile(r"^(#{2,3})[ \t]+(.+?)[ \t]*#*[ \t]*$")


def parse_sections(markdown: str) -> list[SectionRef]:
    """Only third-level headings directly below second-level Modules/Threads count."""
    current_kind: str | None = None
    found: list[SectionRef] = []
    seen: set[tuple[str, str]] = set()
    in_fence = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING.fullmatch(line)
        if not match:
            continue
        level, title = match.groups()
        title = title.strip()
        if level == "##":
            current_kind = {"Modules": "module", "Threads": "thread"}.get(title)
        elif current_kind and title:
            key = (current_kind, title)
            if key not in seen:
                found.append(SectionRef(kind=current_kind, title=title))
                seen.add(key)
    return found


def validate_plan(
    plan: InterviewPlan,
    selected_sections: Iterable[SectionRef],
    topic_paths: set[str],
    max_stages: int,
) -> list[str]:
    errors: list[str] = []
    if not 5 <= len(plan.stages) <= max_stages:
        errors.append(f"stage count must be between 5 and {max_stages}")
    stage_ids = [stage.id for stage in plan.stages]
    if len(stage_ids) != len(set(stage_ids)):
        errors.append("stage IDs must be unique")
    selected = {(section.kind, section.title) for section in selected_sections}
    covered: set[tuple[str, str]] = set()
    for index, stage in enumerate(plan.stages):
        if stage.topic_path not in topic_paths:
            errors.append(f"stage {index}: unknown topic_path")
        for section in stage.section_refs:
            key = (section.kind, section.title)
            if key not in selected:
                errors.append(f"stage {index}: section_ref is not selected")
            else:
                covered.add(key)
    if selected - covered:
        errors.append("some selected sections are not covered")
    return errors


def exact_question_id(question: str, candidates: Iterable[tuple[UUID, str]]) -> UUID | None:
    for question_id, candidate_text in candidates:
        if question == candidate_text:
            return question_id
    return None
