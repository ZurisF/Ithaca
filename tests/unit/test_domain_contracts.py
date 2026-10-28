from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.contracts import InterviewPlan, InterviewStage, SectionRef, SupervisorDecision
from app.domain.rules import exact_question_id, parse_sections, validate_plan


def make_plan(stages: int = 5) -> InterviewPlan:
    return InterviewPlan(
        stages=[
            InterviewStage(
                id=f"stage-{index}",
                title=f"阶段 {index}",
                goal="核实项目决策",
                complete_when="能解释证据和取舍",
                topic_path="system_design",
                section_refs=[SectionRef(kind="thread", title="Query Flow")],
            )
            for index in range(stages)
        ],
        template_id="core_flow_deep_dive",
        template_version="v1",
        topic_registry_version="v1",
        planning_policy_version="v1",
    )


def test_parse_only_specified_heading_levels_and_deduplicate() -> None:
    markdown = """# Project
## Modules
### API
#### Internal detail
### API
## Other
### Not a range
## Threads
### API
```md
### Fake
```
"""
    assert parse_sections(markdown) == [
        SectionRef(kind="module", title="API"),
        SectionRef(kind="thread", title="API"),
    ]


def test_plan_has_valid_stages_topics_and_selected_coverage() -> None:
    selected = [SectionRef(kind="thread", title="Query Flow")]
    plan = make_plan()
    assert validate_plan(plan, selected, {"system_design"}, 12) == []
    assert "stage count" in validate_plan(make_plan(4), selected, {"system_design"}, 12)[0]
    assert "unknown topic" in validate_plan(plan, selected, set(), 12)[0]
    plan.stages[1].id = plan.stages[0].id
    assert "stage IDs" in validate_plan(plan, selected, {"system_design"}, 12)[0]
    with pytest.raises(ValidationError):
        InterviewStage.model_validate({**plan.stages[0].model_dump(), "fixed_question": "问题？"})


def test_supervisor_action_and_stage_entry_are_strict() -> None:
    decision = SupervisorDecision(
        user_acts=[], interviewer_message=None, plan_action="continue", question="为什么？"
    )
    decision.validate_stage_entry()
    with pytest.raises(ValidationError):
        SupervisorDecision(user_acts=[], plan_action="complete", question="错误的问题？")
    with pytest.raises(ValidationError):
        SupervisorDecision(user_acts=[], plan_action="continue", question="   ")
    with pytest.raises(ValueError):
        SupervisorDecision(
            user_acts=[{"type": "answer"}], plan_action="continue", question="为什么？"
        ).validate_stage_entry()


def test_question_bank_link_requires_exact_text() -> None:
    question_id = uuid4()
    question = "为什么选 pgvector？"
    candidates = [(question_id, question)]
    assert exact_question_id(question, candidates) == question_id
    assert exact_question_id("为什么选择 pgvector？", candidates) is None
    assert exact_question_id("为什么选 pgvector?", candidates) is None
