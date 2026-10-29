"""Gate 6 SSE named-event contract: design doc, endpoint whitelist, producers agree.

Design 10.6 defines the only named events `GET /events` may forward. The three
sides are locked here: the document block, the endpoint whitelist constant and
every literal the producers can publish. An event published outside the
whitelist is silently dropped, so drift must fail a test instead of the UI.
"""

import ast
import asyncio
import re
from contextlib import suppress
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.interview import SSE_EVENT_NAMES
from app.db import engine
from app.main import app
from app.settings import get_settings

USER_ID = UUID("00000000-0000-4000-8000-000000000001")
HEADERS = {"X-Dev-User": str(USER_ID)}
ROOT = Path(__file__).resolve().parents[2]
APPLICATION_SERVICES = ROOT / "services" / "application" / "src" / "app" / "services"


def design_doc_event_names() -> set[str]:
    source = (ROOT / "IMPLEMENTATION_DESIGN.md").read_text(encoding="utf-8")
    block = re.search(r"### 10\.6 事件流.*?```text\n(.*?)```", source, flags=re.DOTALL)
    assert block is not None, "IMPLEMENTATION_DESIGN.md section 10.6 event block is missing"
    return {line.strip() for line in block.group(1).splitlines() if line.strip()}


def _published_value_strings(node: ast.AST) -> set[str]:
    """String constants in value positions: IfExp branches, tuple elements, bare constants."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _published_value_strings(node.body) | _published_value_strings(node.orelse)
    if isinstance(node, ast.Tuple):
        return set().union(*(_published_value_strings(item) for item in node.elts))
    return set()


def producer_event_names() -> set[str]:
    """Every event name reachable to notify_current_changed in the service layer."""
    names: set[str] = set()
    for path in sorted(APPLICATION_SERVICES.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_changed"
            ):
                for default in node.args.defaults:
                    names |= _published_value_strings(default)
            if isinstance(node, ast.Call):
                function = node.func
                called = (
                    function.id
                    if isinstance(function, ast.Name)
                    else (function.attr if isinstance(function, ast.Attribute) else "")
                )
                if called in {"_changed", "notify_current_changed"} or (
                    called == "append"
                    and isinstance(function, ast.Attribute)
                    and isinstance(function.value, ast.Name)
                    and function.value.id == "events"
                ):
                    for argument in node.args:
                        names |= _published_value_strings(argument)
    return names


def test_endpoint_whitelist_matches_design_doc():
    assert SSE_EVENT_NAMES == design_doc_event_names()


def test_producers_publish_exactly_the_whitelist():
    assert producer_event_names() == SSE_EVENT_NAMES


def test_no_residual_unnamed_event_literals():
    """A bare current_changed publish would be silently dropped by the whitelist."""
    for path in sorted((ROOT / "services" / "application" / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "current_changed":
                pytest.fail(f"residual unnamed event literal in {path}")


async def test_events_endpoint_forwards_whitelist_and_drops_unknown_names():
    """The live stream forwards each whitelisted name and silently drops others."""
    marker = "question_ready"
    ordered = sorted(SSE_EVENT_NAMES)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/v1/interviews", headers=HEADERS)
        assert created.status_code == 201, created.text
        session_id = created.json()["id"]
        try:
            # httpx's ASGITransport buffers the whole body, so drive the ASGI
            # interface directly to observe the stream frame by frame.
            chunks: asyncio.Queue[bytes] = asyncio.Queue()
            status: list[int] = []
            request_delivered = False

            async def receive() -> dict:
                nonlocal request_delivered
                if not request_delivered:
                    request_delivered = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                # Starlette polls receive() for disconnects; block so the loop is
                # not starved by a busy listener.
                await asyncio.sleep(3600)
                return {"type": "http.disconnect"}

            async def send(message: dict) -> None:
                if message["type"] == "http.response.start":
                    status.append(message["status"])
                elif message["type"] == "http.response.body" and message.get("body"):
                    await chunks.put(message["body"])

            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": f"/v1/interviews/{session_id}/events",
                "raw_path": f"/v1/interviews/{session_id}/events".encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [(b"x-dev-user", str(USER_ID).encode())],
                "client": ("testclient", 50000),
                "server": ("testserver", 80),
            }
            streaming = asyncio.create_task(app(scope, receive, send))

            async def collect_frames() -> list[str]:
                forwarded: list[str] = []
                buffer = ""
                while len(forwarded) < len(ordered) + 1:
                    buffer += (await asyncio.wait_for(chunks.get(), timeout=20)).decode("utf-8")
                    while "\n\n" in buffer:
                        frame, buffer = buffer.split("\n\n", 1)
                        if frame.startswith("event: "):
                            forwarded.append(frame.removeprefix("event: ").splitlines()[0])
                        elif ": connected" in frame:
                            redis = Redis.from_url(get_settings().redis_url)
                            try:
                                for name in ordered:
                                    await redis.publish(f"interview:{session_id}:events", name)
                                # Not whitelisted: must never surface as a frame.
                                await redis.publish(
                                    f"interview:{session_id}:events", "current_changed"
                                )
                                await redis.publish(f"interview:{session_id}:events", marker)
                            finally:
                                await redis.aclose()
                return forwarded

            try:
                forwarded = await asyncio.wait_for(collect_frames(), timeout=30)
                assert status == [200]
            finally:
                streaming.cancel()
                with suppress(asyncio.CancelledError):
                    await streaming
        finally:
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM app.interview_sessions WHERE id = :id"), {"id": session_id}
                )
    assert forwarded[: len(ordered)] == ordered
    assert forwarded == ordered + [marker], "current_changed must be silently dropped"
