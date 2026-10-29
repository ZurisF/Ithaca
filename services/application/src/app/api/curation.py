"""Curation HTTP contracts."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.identity import Identity, get_identity
from app.api.model_dependency import get_model_adapter
from app.bank.retrieval import QuestionRetriever, get_retriever
from app.db import get_db
from app.domain.contracts import BankQuestion, CurationItem, CurationQueue, SessionView
from app.services import curation
from model_adapter import ModelAdapter

router = APIRouter(tags=["curation"])
Database = Annotated[AsyncSession, Depends(get_db)]
CurrentIdentity = Annotated[Identity, Depends(get_identity)]
CurrentRetriever = Annotated[QuestionRetriever, Depends(get_retriever)]
CurrentModel = Annotated[ModelAdapter, Depends(get_model_adapter)]


class SaveItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_session_id: UUID
    source_turn_no: int = Field(ge=1, le=100)
    item_id: UUID | None = None
    status: Literal["reviewed", "rejected"] | None = None
    edited_question: str | None = Field(default=None, max_length=1000)
    proposed_topic_path: str | None = Field(default=None, max_length=200)
    review_notes: str | None = Field(default=None, max_length=2000)
    suggest: bool = False


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ideal_answer: str | None = Field(default=None, max_length=8000)


@router.put("/v1/interviews/{session_id}/curation-grant", response_model=SessionView)
async def grant(session_id: UUID, db: Database, identity: CurrentIdentity) -> SessionView:
    return await curation.grant(db, identity, session_id, True)


@router.delete("/v1/interviews/{session_id}/curation-grant", response_model=SessionView)
async def revoke(session_id: UUID, db: Database, identity: CurrentIdentity) -> SessionView:
    return await curation.grant(db, identity, session_id, False)


@router.get("/v1/admin/curation-items", response_model=CurationQueue)
async def queue(
    db: Database,
    identity: CurrentIdentity,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CurationQueue:
    return await curation.queue(db, identity, limit=limit, offset=offset)


@router.post("/v1/admin/curation-items", response_model=CurationItem)
async def save_item(
    body: SaveItemRequest, db: Database, identity: CurrentIdentity, model: CurrentModel
) -> CurationItem:
    return await curation.save_item(
        db,
        identity,
        body.source_session_id,
        body.source_turn_no,
        item_id=body.item_id,
        status=body.status,
        edited_question=body.edited_question,
        proposed_topic_path=body.proposed_topic_path,
        review_notes=body.review_notes,
        suggest=body.suggest,
        model=model,
    )


@router.post("/v1/admin/curation-items/{item_id}:add-to-question-bank", response_model=CurationItem)
async def publish(
    item_id: UUID,
    body: PublishRequest,
    db: Database,
    identity: CurrentIdentity,
    retriever: CurrentRetriever,
) -> CurationItem:
    return await curation.publish(db, identity, item_id, body.ideal_answer, retriever.models)


@router.get("/v1/admin/question-bank", response_model=list[BankQuestion])
async def question_bank(
    db: Database,
    identity: CurrentIdentity,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[BankQuestion]:
    return await curation.question_bank(db, identity, limit=limit, offset=offset)
