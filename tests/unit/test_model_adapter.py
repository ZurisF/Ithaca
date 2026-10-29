import json

import httpx
import pytest
from pydantic import BaseModel

from app.api.model_dependency import get_model_adapter
from local_project.api.sources import get_observer_model
from model_adapter import Message, ModelFailure, OpenAICompatibleAdapter, RetryPolicy


class Output(BaseModel):
    value: str


class CaptureTrace:
    def __init__(self) -> None:
        self.spans = []

    async def write(self, span) -> None:
        self.spans.append(span)


def test_runtime_model_factories_share_their_concurrency_limit() -> None:
    assert get_model_adapter() is get_model_adapter()
    assert get_observer_model() is get_observer_model()


@pytest.mark.asyncio
async def test_retry_and_trace_do_not_store_content() -> None:
    requests = []

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"value": "合格"})}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        )

    trace = CaptureTrace()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        adapter = OpenAICompatibleAdapter(
            base_url="http://provider/v1",
            api_key="test-only-key",
            model="test-model",
            provider="controlled",
            trace_sink=trace,
            client=client,
        )
        output = await adapter.generate_structured(
            session_id=None,
            operation="planner",
            messages=[Message(role="user", content="PRIVATE CANARY")],
            output_schema=Output,
            prompt_version="v1",
            retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0),
            max_completion_tokens=128,
        )
    assert output.value == "合格"
    assert len(requests) == len(trace.spans) == 2
    assert [span.status for span in trace.spans] == ["failed", "succeeded"]
    assert "PRIVATE CANARY" not in repr(trace.spans)
    assert "合格" not in repr(trace.spans)
    assert json.loads(requests[0].content)["max_completion_tokens"] == 128


@pytest.mark.asyncio
async def test_invalid_json_consumes_repair_attempt() -> None:
    calls = 0

    def provider(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = "not json" if calls == 1 else '{"value":"ok"}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    trace = CaptureTrace()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        adapter = OpenAICompatibleAdapter(
            base_url="http://provider/v1",
            api_key="test-only-key",
            model="test-model",
            provider="controlled",
            trace_sink=trace,
            client=client,
        )
        result = await adapter.generate_structured(
            session_id=None,
            operation="planner",
            messages=[Message(role="user", content="data")],
            output_schema=Output,
            prompt_version="v1",
            retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0),
        )
    assert result.value == "ok"
    assert calls == 2
    assert trace.spans[0].error_code == "schema_invalid"


@pytest.mark.asyncio
async def test_auth_failure_is_not_retried() -> None:
    calls = 0

    def provider(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        adapter = OpenAICompatibleAdapter(
            base_url="http://provider/v1",
            api_key="test-only-key",
            model="test-model",
            provider="controlled",
            trace_sink=CaptureTrace(),
            client=client,
        )
        with pytest.raises(ModelFailure) as failure:
            await adapter.generate_structured(
                session_id=None,
                operation="planner",
                messages=[],
                output_schema=Output,
                prompt_version="v1",
                retry_policy=RetryPolicy(max_attempts=3),
            )
    assert failure.value.code == "provider_auth"
    assert calls == 1
