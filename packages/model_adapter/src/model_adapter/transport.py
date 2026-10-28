"""Shared, content-free model transport with one retry and validation budget."""

import asyncio
import json
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal, Protocol, TypeVar
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ValidationError

OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    deadline_seconds: float = 60
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 5

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.deadline_seconds <= 0:
            raise ValueError("retry budget must be positive")


@dataclass(frozen=True)
class TraceSpan:
    trace_id: UUID
    session_id: UUID | None
    operation_name: str
    provider: str
    model: str
    prompt_version: str | None
    status: Literal["succeeded", "failed"]
    attempt_no: int
    started_at: datetime
    finished_at: datetime
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    error_code: str | None


class TraceSink(Protocol):
    async def write(self, span: TraceSpan) -> None: ...


class ModelFailure(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class ModelAdapter(Protocol):
    async def generate_structured(
        self,
        *,
        session_id: UUID | None,
        operation: str,
        messages: list[Message],
        output_schema: type[OutputT],
        prompt_version: str,
        retry_policy: RetryPolicy,
        validate_output: Callable[[OutputT], list[str]] | None = None,
        max_completion_tokens: int | None = None,
    ) -> OutputT: ...


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0, float(value))
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            return max(0, (when - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _status_failure(status: int) -> ModelFailure:
    if status in {408, 429} or 500 <= status <= 599:
        return ModelFailure("provider_retryable", retryable=True)
    if status in {401, 403}:
        return ModelFailure("provider_auth")
    if status == 404:
        return ModelFailure("model_not_found")
    return ModelFailure("provider_rejected")


class OpenAICompatibleAdapter:
    """Chat-completions JSON transport; provider SDK retries are not involved."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        provider: str,
        trace_sink: TraceSink,
        max_concurrency: int = 4,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.trace_sink = trace_sink
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.client = client

    async def generate_structured(
        self,
        *,
        session_id: UUID | None,
        operation: str,
        messages: list[Message],
        output_schema: type[OutputT],
        prompt_version: str,
        retry_policy: RetryPolicy,
        validate_output: Callable[[OutputT], list[str]] | None = None,
        max_completion_tokens: int | None = None,
    ) -> OutputT:
        if not self.api_key or not self.model:
            raise ModelFailure("dependency_unavailable")
        started = time.monotonic()
        repair_messages = list(messages)
        async with self.semaphore:
            for attempt in range(1, retry_policy.max_attempts + 1):
                remaining = retry_policy.deadline_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise ModelFailure("model_deadline_exceeded")
                attempt_started = datetime.now(UTC)
                tick = time.monotonic()
                error_code: str | None = None
                tokens_in: int | None = None
                tokens_out: int | None = None
                retry_after: float | None = None
                result: OutputT | None = None
                failure: ModelFailure | None = None
                try:
                    payload = {
                        "model": self.model,
                        "messages": [message.__dict__ for message in repair_messages],
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": output_schema.__name__,
                                "schema": output_schema.model_json_schema(),
                                "strict": False,
                            },
                        },
                    }
                    if max_completion_tokens is not None:
                        if max_completion_tokens < 1:
                            raise ModelFailure("invalid_model_budget")
                        payload["max_completion_tokens"] = max_completion_tokens
                    if self.client is None:
                        async with httpx.AsyncClient(timeout=remaining) as client:
                            response = await client.post(
                                f"{self.base_url}/chat/completions",
                                json=payload,
                                headers={"Authorization": f"Bearer {self.api_key}"},
                            )
                    else:
                        response = await self.client.post(
                            f"{self.base_url}/chat/completions",
                            json=payload,
                            headers={"Authorization": f"Bearer {self.api_key}"},
                            timeout=remaining,
                        )
                    if response.status_code >= 400:
                        retry_after = _retry_after(response.headers.get("Retry-After"))
                        raise _status_failure(response.status_code)
                    envelope = response.json()
                    usage = envelope.get("usage") or {}
                    tokens_in = usage.get("prompt_tokens")
                    tokens_out = usage.get("completion_tokens")
                    content = envelope["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    result = output_schema.model_validate(parsed)
                    if validate_output is not None:
                        errors = validate_output(result)
                        if errors:
                            result = None
                            failure = ModelFailure("output_invalid", retryable=True)
                            error_code = failure.code
                            repair_messages = [
                                *messages,
                                Message(
                                    role="user",
                                    content=(
                                        "Revise the previous JSON to satisfy these deterministic "
                                        f"validation errors: {json.dumps(errors, ensure_ascii=False)}"
                                    ),
                                ),
                            ]
                except (
                    httpx.TimeoutException,
                    httpx.ConnectError,
                    httpx.RemoteProtocolError,
                ):
                    failure = ModelFailure("provider_transport", retryable=True)
                    error_code = failure.code
                except ModelFailure as exc:
                    failure = exc
                    error_code = failure.code
                except (KeyError, IndexError, TypeError, ValueError, ValidationError):
                    # The response body is never put in errors or trace. A repair consumes this budget.
                    failure = ModelFailure("schema_invalid", retryable=True)
                    error_code = failure.code
                    repair_messages = [
                        *messages,
                        Message(
                            role="user",
                            content=(
                                "The previous response was not valid for the supplied JSON schema. "
                                "Return one complete JSON object matching that schema."
                            ),
                        ),
                    ]
                finally:
                    finished = datetime.now(UTC)
                    span = TraceSpan(
                        trace_id=uuid4(),
                        session_id=session_id,
                        operation_name=operation,
                        provider=self.provider,
                        model=self.model,
                        prompt_version=prompt_version,
                        status="succeeded" if result is not None else "failed",
                        attempt_no=attempt,
                        started_at=attempt_started,
                        finished_at=finished,
                        latency_ms=max(0, round((time.monotonic() - tick) * 1000)),
                        input_tokens=tokens_in,
                        output_tokens=tokens_out,
                        error_code=error_code,
                    )
                    try:
                        await self.trace_sink.write(span)
                    except Exception:  # noqa: BLE001 - trace must never change business outcome
                        logging.getLogger(__name__).warning("trace_write_failed")
                if result is not None:
                    return result
                assert failure is not None
                if not failure.retryable or attempt == retry_policy.max_attempts:
                    raise failure
                remaining = retry_policy.deadline_seconds - (time.monotonic() - started)
                delay = retry_after
                if delay is None:
                    delay = min(
                        retry_policy.max_delay_seconds,
                        retry_policy.base_delay_seconds * 2 ** (attempt - 1),
                    ) * random.uniform(0.5, 1.5)
                if remaining <= delay:
                    raise ModelFailure("model_deadline_exceeded")
                await asyncio.sleep(delay)
        raise ModelFailure("model_attempts_exhausted")
