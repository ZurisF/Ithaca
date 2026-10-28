"""Preparing workflow: owner checks, state, content, invalidation and transactions."""

import hashlib
import json
import re
from uuid import UUID, uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.api.identity import Identity
from app.domain.contracts import Direction, SectionRef, SessionSummary, SessionView, SnapshotView
from app.domain.rules import parse_sections
from app.repositories import prepare as repo
from app.settings import get_settings
from content_safety import ContentRejected, filter_text


def _require_user(identity: Identity) -> None:
    if identity.role != "user":
        raise AppError(403, "forbidden", "只有 User 可以创建和管理面试会话。")


def _session_view(row) -> SessionView:
    return SessionView.model_validate(dict(row))


def _require_preparing(row) -> None:
    if row["status"] != "preparing":
        raise AppError(409, "state_conflict", "当前会话已离开准备阶段。")


async def _owned_session(db: AsyncSession, session_id: UUID, identity: Identity, *, lock: bool):
    _require_user(identity)
    row = await repo.get_session(db, session_id, identity.id, lock=lock)
    if row is None:
        raise AppError(404, "session_not_found", "找不到这场面试。")
    return row


def _safe_text(raw: str, *, max_chars: int) -> str:
    try:
        return filter_text(raw, max_chars=max_chars).text
    except ContentRejected as exc:
        raise AppError(422, "safety_filter_rejected", "材料未通过内容安全检查。") from exc


async def create(db: AsyncSession, identity: Identity) -> SessionView:
    _require_user(identity)
    session_id = uuid4()
    async with db.begin():
        await repo.create_session(db, session_id, identity.id)
        row = await repo.get_session(db, session_id, identity.id)
    return _session_view(row)


async def get(db: AsyncSession, identity: Identity, session_id: UUID) -> SessionView:
    row = await _owned_session(db, session_id, identity, lock=False)
    return _session_view(row)


async def list_for_user(
    db: AsyncSession, identity: Identity, *, limit: int, offset: int
) -> list[SessionSummary]:
    _require_user(identity)
    rows = await repo.list_sessions(db, identity.id, limit, offset)
    return [SessionSummary.model_validate(dict(row)) for row in rows]


async def import_markdown(
    db: AsyncSession, identity: Identity, session_id: UUID, markdown: str, source_handle: str | None
) -> SnapshotView:
    async with db.begin():
        initial = await _owned_session(db, session_id, identity, lock=False)
        _require_preparing(initial)
    content = _safe_text(markdown, max_chars=200_000)
    if source_handle is not None:
        await _verify_source_handle(session_id, source_handle)
    async with db.begin():
        row = await _owned_session(db, session_id, identity, lock=True)
        _require_preparing(row)
        old_content = await repo.get_snapshot(db, session_id)
        if old_content != content:
            await repo.replace_snapshot(db, session_id, content)
            await repo.clear_selection_and_plan(db, session_id)
        if source_handle is not None:
            await repo.set_source_handle(db, session_id, source_handle)
    return SnapshotView(session_id=session_id, content=content, sections=parse_sections(content))


async def _verify_source_handle(session_id: UUID, source_handle: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", source_handle) is None:
        raise AppError(400, "invalid_request", "目录授权标识无效。")
    settings = get_settings()
    if not settings.desktop_instance_token:
        raise AppError(503, "dependency_unavailable", "本地目录服务尚未配置。")
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            response = await client.get(
                f"{settings.local_runtime_url}/v1/sources/{source_handle}/inventory",
                params={"session_id": str(session_id)},
                headers={"Authorization": f"Bearer {settings.desktop_instance_token}"},
            )
    except httpx.RequestError as exc:
        raise AppError(503, "dependency_unavailable", "本地目录服务暂时不可用。", True) from exc
    if response.status_code == 404:
        raise AppError(403, "forbidden", "目录授权不属于当前会话或已失效。")
    if response.status_code != 200:
        raise AppError(503, "dependency_unavailable", "本地目录授权无法验证。", True)


async def observe_source(
    db: AsyncSession, identity: Identity, session_id: UUID, source_handle: str, operation_id: UUID
) -> SnapshotView:
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", source_handle) is None:
        raise AppError(400, "invalid_request", "目录授权标识无效。")
    async with db.begin():
        row = await _owned_session(db, session_id, identity, lock=False)
        _require_preparing(row)
    settings = get_settings()
    if not settings.desktop_instance_token:
        raise AppError(503, "dependency_unavailable", "本地目录服务尚未配置。")
    try:
        async with httpx.AsyncClient(timeout=190, trust_env=False) as client:
            response = await client.post(
                f"{settings.local_runtime_url}/v1/sources/{source_handle}:observe",
                headers={"Authorization": f"Bearer {settings.desktop_instance_token}"},
                json={"session_id": str(session_id), "operation_id": str(operation_id)},
            )
    except httpx.RequestError as exc:
        raise AppError(503, "dependency_unavailable", "本地项目观察暂时不可用。", True) from exc
    if response.status_code == 404:
        raise AppError(403, "forbidden", "目录授权不属于当前会话或已失效。")
    if response.status_code != 200:
        code = (
            response.json().get("error", {}).get("code")
            if response.headers.get("content-type", "").startswith("application/json")
            else None
        )
        if code == "dependency_unavailable":
            raise AppError(503, "dependency_unavailable", "模型尚未配置。")
        raise AppError(503, "observer_failed", "目录观察未能完成。", True)
    payload = response.json()
    if payload.get("operation_id") != str(operation_id) or not isinstance(
        payload.get("snapshot"), str
    ):
        raise AppError(503, "observer_failed", "目录观察返回无效。")
    return await import_markdown(db, identity, session_id, payload["snapshot"], source_handle)


async def parse_ranges(db: AsyncSession, identity: Identity, session_id: UUID) -> SnapshotView:
    await _owned_session(db, session_id, identity, lock=False)
    content = await repo.get_snapshot(db, session_id)
    if content is None:
        raise AppError(409, "state_conflict", "请先导入或生成项目快照。")
    return SnapshotView(session_id=session_id, content=content, sections=parse_sections(content))


async def select(
    db: AsyncSession,
    identity: Identity,
    session_id: UUID,
    direction: Direction,
    selected_sections: list[SectionRef],
    confirm_empty_range: bool,
) -> SessionView:
    async with db.begin():
        row = await _owned_session(db, session_id, identity, lock=True)
        _require_preparing(row)
        content = await repo.get_snapshot(db, session_id)
        if content is None:
            raise AppError(409, "state_conflict", "请先导入或生成项目快照。")
        available = parse_sections(content)
        allowed = {(item.kind, item.title) for item in available}
        chosen = {(item.kind, item.title) for item in selected_sections}
        if not chosen <= allowed or (available and not chosen):
            raise AppError(400, "invalid_request", "选定范围与当前快照不符。")
        if not available and not confirm_empty_range:
            raise AppError(400, "invalid_request", "请先确认以整份 Markdown 继续。")
        normalized = [item for item in available if (item.kind, item.title) in chosen]
        if row["interview_direction"] != direction.value or row["selected_sections"] != [
            item.model_dump() for item in normalized
        ]:
            await repo.save_selection(
                db,
                session_id,
                direction.value,
                json.dumps([item.model_dump() for item in normalized], ensure_ascii=False),
            )
        updated = await repo.get_session(db, session_id, identity.id)
    return _session_view(updated)


def append_to_section(content: str, section: str, addition: str) -> str:
    stripped = content.rstrip("\n")
    last_heading = [line for line in stripped.splitlines() if line.startswith("## ")]
    if last_heading and last_heading[-1].strip() == f"## {section}":
        return f"{stripped}\n\n{addition.strip()}\n"
    return f"{stripped}\n\n## {section}\n\n{addition.strip()}\n"


async def append_user_opinion(
    db: AsyncSession, identity: Identity, session_id: UUID, raw: str, idempotency_key: str
) -> SnapshotView:
    try:
        request_id = UUID(idempotency_key)
    except ValueError as exc:
        raise AppError(400, "invalid_request", "Idempotency-Key 必须是 UUID。") from exc
    addition = _safe_text(raw, max_chars=4_000)
    payload_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    operation_key = f"session:{session_id}:snapshot:user_opinion:{request_id}"
    async with db.begin():
        row = await _owned_session(db, session_id, identity, lock=True)
        _require_preparing(row)
        content = await repo.get_snapshot(db, session_id)
        if content is None:
            raise AppError(409, "state_conflict", "请先导入或生成项目快照。")
        receipt = await repo.get_append_receipt(db, operation_key)
        if receipt:
            if receipt["session_id"] != session_id or receipt["payload_hash"] != payload_hash:
                raise AppError(409, "answer_conflict", "同一追加请求不能使用不同内容。")
        else:
            content = append_to_section(content, "用户意见", addition)
            if len(content) > 200_000:
                raise AppError(422, "safety_filter_rejected", "快照已达到长度上限。")
            await repo.insert_append_receipt(db, operation_key, session_id, payload_hash)
            await repo.replace_snapshot(db, session_id, content)
            await repo.clear_selection_and_plan(db, session_id)
    return SnapshotView(session_id=session_id, content=content, sections=parse_sections(content))
