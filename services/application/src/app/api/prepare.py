"""Public preparing endpoints; transaction and authorization live in the service."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.identity import Identity, get_identity
from app.api.model_dependency import get_model_adapter
from app.db import get_db
from app.domain.contracts import (
    Direction,
    InterviewPlan,
    SectionRef,
    SessionSummary,
    SessionView,
    SnapshotView,
    SourceInventory,
)
from app.services import planning, session_deletion
from app.services import prepare as service
from model_adapter import ModelAdapter

router = APIRouter(prefix="/v1/interviews", tags=["interviews"])
Database = Annotated[AsyncSession, Depends(get_db)]
CurrentIdentity = Annotated[Identity, Depends(get_identity)]
CurrentModel = Annotated[ModelAdapter, Depends(get_model_adapter)]


class SnapshotImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    markdown: str = Field(min_length=1, max_length=200_000)
    source_handle: str | None = Field(default=None, max_length=200)


class UserOpinionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4_000)


class SnapshotObserveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_handle: str = Field(min_length=1, max_length=200)


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interview_direction: Direction
    selected_sections: list[SectionRef]
    confirm_empty_range: bool = False


@router.post("", response_model=SessionView, status_code=201)
async def create_session(db: Database, identity: CurrentIdentity) -> SessionView:
    return await service.create(db, identity)


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    db: Database,
    identity: CurrentIdentity,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SessionSummary]:
    return await service.list_for_user(db, identity, limit=limit, offset=offset)


@router.get("/{session_id}", response_model=SessionView)
async def get_session(session_id: UUID, db: Database, identity: CurrentIdentity) -> SessionView:
    return await service.get(db, identity, session_id)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: UUID, db: Database, identity: CurrentIdentity) -> None:
    await session_deletion.delete(db, identity, session_id)


@router.post("/{session_id}/snapshot:import", response_model=SnapshotView)
async def import_snapshot(
    session_id: UUID, body: SnapshotImportRequest, db: Database, identity: CurrentIdentity
) -> SnapshotView:
    return await service.import_markdown(
        db, identity, session_id, body.markdown, body.source_handle
    )


@router.post("/{session_id}/snapshot:parse-ranges", response_model=SnapshotView)
async def parse_ranges(session_id: UUID, db: Database, identity: CurrentIdentity) -> SnapshotView:
    return await service.parse_ranges(db, identity, session_id)


@router.post("/{session_id}/source:choose", response_model=SourceInventory)
async def choose_source(
    session_id: UUID, db: Database, identity: CurrentIdentity
) -> SourceInventory:
    return await service.choose_source(db, identity, session_id)


@router.get("/{session_id}/source/inventory", response_model=SourceInventory)
async def source_inventory(
    session_id: UUID, db: Database, identity: CurrentIdentity
) -> SourceInventory:
    return await service.source_inventory(db, identity, session_id)


@router.post("/{session_id}/snapshot:observe", response_model=SnapshotView)
async def observe_snapshot(
    session_id: UUID,
    body: SnapshotObserveRequest,
    db: Database,
    identity: CurrentIdentity,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> SnapshotView:
    return await service.observe_source(
        db, identity, session_id, body.source_handle, idempotency_key
    )


@router.post("/{session_id}/snapshot:append-user-opinion", response_model=SnapshotView)
async def append_opinion(
    session_id: UUID,
    body: UserOpinionRequest,
    db: Database,
    identity: CurrentIdentity,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=80)],
) -> SnapshotView:
    return await service.append_user_opinion(db, identity, session_id, body.text, idempotency_key)


@router.put("/{session_id}/selection", response_model=SessionView)
async def select_scope(
    session_id: UUID, body: SelectionRequest, db: Database, identity: CurrentIdentity
) -> SessionView:
    return await service.select(
        db,
        identity,
        session_id,
        body.interview_direction,
        body.selected_sections,
        body.confirm_empty_range,
    )


@router.get("/{session_id}/snapshot.md", response_class=PlainTextResponse)
async def export_snapshot(session_id: UUID, db: Database, identity: CurrentIdentity) -> str:
    return (await service.parse_ranges(db, identity, session_id)).content


@router.post("/{session_id}/plan:generate", response_model=InterviewPlan)
async def generate_plan(
    session_id: UUID, db: Database, identity: CurrentIdentity, model: CurrentModel
) -> InterviewPlan:
    return await planning.generate_plan(db, identity, session_id, model)


@router.get("/{session_id}/plan", response_model=InterviewPlan)
async def get_plan(session_id: UUID, db: Database, identity: CurrentIdentity) -> InterviewPlan:
    return await planning.get_plan(db, identity, session_id)
