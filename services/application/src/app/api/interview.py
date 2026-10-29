"""Current interview projection and Stage entry commands."""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.identity import Identity, get_identity
from app.api.model_dependency import get_model_adapter
from app.bank.retrieval import QuestionRetriever, get_retriever
from app.db import get_db
from app.domain.contracts import FeedbackView, InterviewView, Report, ResultView, SessionView
from app.services import finalization
from app.services import interview as service
from app.services.errors import AppError
from app.services.result_render import render_full_qa_markdown, render_report_markdown
from app.services.session_access import owned_session
from app.settings import get_settings
from model_adapter import ModelAdapter

router = APIRouter(prefix="/v1/interviews", tags=["interviews"])
Database = Annotated[AsyncSession, Depends(get_db)]
CurrentIdentity = Annotated[Identity, Depends(get_identity)]
CurrentModel = Annotated[ModelAdapter, Depends(get_model_adapter)]
CurrentRetriever = Annotated[QuestionRetriever, Depends(get_retriever)]


class AnswerRequest(BaseModel):
    turn_no: int = Field(ge=1, le=100)
    answer: str = Field(min_length=1, max_length=8_000)


class CorrectionRequest(BaseModel):
    turn_no: int = Field(ge=1, le=100)
    decision: Literal["confirm", "do_not_write"]
    edited_text: str | None = Field(default=None, min_length=1, max_length=4_000)


class FeedbackRequest(BaseModel):
    value: Literal["upvote", "downvote"]
    reason: Literal["重复", "不相关", "表述不清", "其他"] | None = None


@router.get("/{session_id}/current", response_model=InterviewView)
async def current(session_id: UUID, db: Database, identity: CurrentIdentity) -> InterviewView:
    return await service.get_current_view(db, identity, session_id)


@router.post("/{session_id}/start", response_model=InterviewView)
async def start(
    session_id: UUID,
    db: Database,
    identity: CurrentIdentity,
    model: CurrentModel,
    retriever: CurrentRetriever,
) -> InterviewView:
    return await service.start(db, identity, session_id, model, retriever)


@router.post("/{session_id}/decision:retry", response_model=InterviewView)
async def retry_decision(
    session_id: UUID,
    db: Database,
    identity: CurrentIdentity,
    model: CurrentModel,
    retriever: CurrentRetriever,
) -> InterviewView:
    return await service.retry_decision(db, identity, session_id, model, retriever)


@router.post("/{session_id}/answers", response_model=InterviewView)
async def answer(
    session_id: UUID,
    body: AnswerRequest,
    db: Database,
    identity: CurrentIdentity,
    model: CurrentModel,
    retriever: CurrentRetriever,
) -> InterviewView:
    return await service.answer(
        db, identity, session_id, body.turn_no, body.answer, model, retriever
    )


@router.post("/{session_id}/snapshot-corrections:resolve", response_model=InterviewView)
async def resolve_correction(
    session_id: UUID,
    body: CorrectionRequest,
    db: Database,
    identity: CurrentIdentity,
    model: CurrentModel,
    retriever: CurrentRetriever,
) -> InterviewView:
    return await service.resolve_snapshot_correction(
        db,
        identity,
        session_id,
        body.turn_no,
        body.decision,
        body.edited_text,
        model,
        retriever,
    )


@router.post("/{session_id}/finish-early", response_model=SessionView)
async def finish_early(session_id: UUID, db: Database, identity: CurrentIdentity) -> SessionView:
    return await finalization.terminate(db, identity, session_id, "early_finish")


@router.post("/{session_id}/force-exit:confirm", response_model=SessionView)
async def force_exit(session_id: UUID, db: Database, identity: CurrentIdentity) -> SessionView:
    return await finalization.terminate(db, identity, session_id, "forced_exit")


@router.put("/{session_id}/turns/{turn_no}/feedback", response_model=FeedbackView)
async def feedback(
    session_id: UUID,
    turn_no: int,
    body: FeedbackRequest,
    db: Database,
    identity: CurrentIdentity,
) -> FeedbackView:
    return await finalization.put_feedback(
        db, identity, session_id, turn_no, body.value, body.reason
    )


@router.get("/{session_id}/full-qa", response_model=ResultView)
async def full_qa(session_id: UUID, db: Database, identity: CurrentIdentity) -> ResultView:
    return await finalization.result_view(db, identity, session_id)


@router.get("/{session_id}/full-qa.md", response_class=PlainTextResponse)
async def full_qa_markdown(
    session_id: UUID, db: Database, identity: CurrentIdentity
) -> PlainTextResponse:
    result = await finalization.result_view(db, identity, session_id)
    return PlainTextResponse(
        render_full_qa_markdown(result), media_type="text/markdown; charset=utf-8"
    )


@router.get("/{session_id}/report", response_model=Report)
async def report(session_id: UUID, db: Database, identity: CurrentIdentity) -> Report:
    result = await finalization.result_view(db, identity, session_id)
    if result.report is None:
        raise AppError(404, "report_not_ready", "复盘报告尚未生成。")
    return result.report


@router.get("/{session_id}/report.md", response_class=PlainTextResponse)
async def report_markdown(
    session_id: UUID, db: Database, identity: CurrentIdentity
) -> PlainTextResponse:
    result = await finalization.result_view(db, identity, session_id)
    if result.report is None:
        raise AppError(404, "report_not_ready", "复盘报告尚未生成。")
    return PlainTextResponse(
        render_report_markdown(result.report), media_type="text/markdown; charset=utf-8"
    )


@router.get("/{session_id}/snapshot.md", response_class=PlainTextResponse)
async def snapshot_markdown(
    session_id: UUID, db: Database, identity: CurrentIdentity
) -> PlainTextResponse:
    content = await finalization.snapshot_markdown(db, identity, session_id)
    return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")


@router.get("/{session_id}/events")
async def events(
    session_id: UUID,
    db: Database,
    identity: CurrentIdentity,
) -> StreamingResponse:
    async with db.begin():
        await owned_session(db, session_id, identity, lock=False)

    async def stream() -> AsyncIterator[str]:
        redis = Redis.from_url(get_settings().redis_url)
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(f"interview:{session_id}:events")
            yield ": connected\n\n"
            while True:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=15), timeout=20
                )
                if message is None:
                    yield ": keepalive\n\n"
                elif message.get("data") == b"current_changed":
                    yield "event: current_changed\ndata: {}\n\n"
        finally:
            await pubsub.aclose()
            await redis.aclose()

    return StreamingResponse(stream(), media_type="text/event-stream")
