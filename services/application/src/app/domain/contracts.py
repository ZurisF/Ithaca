"""Stable domain values and model output contracts.

These are the only shapes accepted from structured model calls. They are not ORM models.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionStatus(StrEnum):
    PREPARING = "preparing"
    INTERVIEWING = "interviewing"
    POST_PROCESSING = "post_processing"
    COMPLETED = "completed"
    ABORTED = "aborted"


class TerminationReason(StrEnum):
    NORMAL = "normal"
    EARLY_FINISH = "early_finish"
    FORCED_EXIT = "forced_exit"
    SAFETY_CAP = "safety_cap"


class Direction(StrEnum):
    PROJECT_OVERVIEW = "project_overview"
    CORE_FLOW_DEEP_DIVE = "core_flow_deep_dive"
    CROSS_CUTTING = "cross_cutting"
    STRESS_INTERVIEW = "stress_interview"
    CONTRIBUTION_RETROSPECTIVE = "contribution_retrospective"


class SectionRef(StrictModel):
    kind: Literal["module", "thread"]
    title: str = Field(min_length=1, max_length=200)


class InterviewStage(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=1000)
    complete_when: str = Field(min_length=1, max_length=1000)
    topic_path: str = Field(min_length=1, max_length=200)
    section_refs: list[SectionRef]


class InterviewPlan(StrictModel):
    stages: list[InterviewStage]
    template_id: str
    template_version: str
    topic_registry_version: str
    planning_policy_version: str


class AnswerAct(StrictModel):
    type: Literal["answer"]


class AskInterviewerAct(StrictModel):
    type: Literal["ask_interviewer"]
    question_kind: Literal["clarification", "process", "answer_or_feedback"]


class CorrectProjectFactAct(StrictModel):
    type: Literal["correct_project_fact"]
    text: str = Field(min_length=1, max_length=4000)


class DeclineCurrentLineAct(StrictModel):
    type: Literal["decline_current_line"]


UserAct = AnswerAct | AskInterviewerAct | CorrectProjectFactAct | DeclineCurrentLineAct


class SupervisorDecision(StrictModel):
    user_acts: list[UserAct]
    interviewer_message: str | None = Field(default=None, max_length=1000)
    plan_action: Literal["continue", "complete", "unresolved"]
    question: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_action(self) -> "SupervisorDecision":
        if self.plan_action == "continue":
            if self.question is None or not self.question.strip():
                raise ValueError("continue requires one non-empty question")
        elif self.question is not None:
            raise ValueError("closing a stage cannot include a question")
        return self

    def validate_stage_entry(self) -> None:
        if self.plan_action != "continue" or self.user_acts or self.interviewer_message is not None:
            raise ValueError(
                "stage entry requires continue, no user acts and no interviewer message"
            )


class ProjectAnswerItem(StrictModel):
    turn_no: int = Field(ge=1, le=100)
    answer: str = Field(min_length=1)


class ProjectAnswersOutput(StrictModel):
    answers: list[ProjectAnswerItem]
    post_verification: str | None = None


class IdealAnswerOutput(StrictModel):
    answer: str = Field(min_length=1)


class EvaluationOutput(StrictModel):
    comment: str = Field(min_length=1)


class DimensionAssessment(StrictModel):
    score: int = Field(ge=0, le=5)
    analysis: str


class ReportDimensions(StrictModel):
    requirements_understanding: DimensionAssessment
    system_design: DimensionAssessment
    technical_depth: DimensionAssessment
    engineering_quality: DimensionAssessment
    failure_thinking: DimensionAssessment
    data_awareness: DimensionAssessment
    communication_structure: DimensionAssessment
    retrospection: DimensionAssessment


class ReportOutput(StrictModel):
    overall: str
    dimensions: ReportDimensions
    project_recommendations: str
    training_recommendations: str


class SessionSummary(StrictModel):
    id: UUID
    status: SessionStatus
    interview_direction: Direction | None
    termination_reason: TerminationReason | None
    created_at: datetime
    updated_at: datetime


class SessionView(SessionSummary):
    selected_sections: list[SectionRef]
    has_snapshot: bool
    has_plan: bool
    source_handle: str | None
    curation_review: bool
    completed_at: datetime | None


class SnapshotView(StrictModel):
    session_id: UUID
    content: str
    sections: list[SectionRef]


class RedactionHit(StrictModel):
    kind: str
    line: int = Field(ge=1)


class SourceFile(StrictModel):
    relative_path: str
    kind: str
    size: int | None
    encoding: str | None
    skip_reason: str | None
    redactions: list[RedactionHit]


class SourceInventory(StrictModel):
    source_handle: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    files: list[SourceFile]
    partial: bool


class ModelReadiness(StrictModel):
    status: Literal["configured"]
    model: str
    provider_host: str


class TurnView(StrictModel):
    turn_no: int
    stage_index: int
    question: str
    answer: str | None
    interviewer_message: str | None
    question_shown_at: datetime
    answered_at: datetime | None


class InterviewView(StrictModel):
    session: SessionView
    plan: InterviewPlan | None
    current_stage_index: int | None
    current_turn: TurnView | None
    awaiting: Literal["answer", "snapshot_confirmation", "decision_retry"] | None
    pending_correction: str | None
    last_error_code: str | None


class FullQaTurnView(TurnView):
    project_answer: str | None
    ideal_answer: str | None
    comment: str | None


class ResultView(StrictModel):
    session: SessionView
    turns: list[FullQaTurnView]
    report: ReportOutput | None
    processing_incomplete: bool
