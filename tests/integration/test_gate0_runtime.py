"""Gate 0 through the public HTTP interfaces and live dependencies."""

import os

import httpx
import pytest

from app.main import app as application_app
from app.main import settings as application_settings
from local_project.main import app as local_app

USER_ID = "00000000-0000-4000-8000-000000000001"
ADMIN_ID = "00000000-0000-4000-8000-000000000002"


@pytest.mark.asyncio
async def test_application_health_and_development_identity() -> None:
    transport = httpx.ASGITransport(app=application_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/health")
        assert health.status_code == 200, health.json()
        assert health.json()["dependencies"] == {"postgresql": "ok", "redis": "ok"}
        assert (await client.get("/v1/me")).status_code == 401
        assert (await client.get("/v1/me", headers={"X-Dev-User": "not-a-uuid"})).status_code == 401
        user = await client.get("/v1/me", headers={"X-Dev-User": USER_ID})
        admin = await client.get("/v1/me", headers={"X-Dev-User": ADMIN_ID})
        assert user.json()["role"] == "user"
        assert admin.json()["role"] == "administrator"


@pytest.mark.asyncio
async def test_health_reports_dependency_failure_without_process_failure(monkeypatch) -> None:
    monkeypatch.setattr(application_settings, "redis_url", "redis://127.0.0.1:1/0")
    transport = httpx.ASGITransport(app=application_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        degraded = await client.get("/health")
    assert degraded.status_code == 503
    assert degraded.json()["process"] == "running"
    assert degraded.json()["dependencies"] == {"postgresql": "ok", "redis": "unavailable"}


@pytest.mark.asyncio
async def test_unconfigured_model_has_explicit_error(monkeypatch) -> None:
    monkeypatch.setattr(application_settings, "model_api_key", "")
    monkeypatch.setattr(application_settings, "model_name", "")
    transport = httpx.ASGITransport(app=application_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/model-readiness")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "dependency_unavailable"


@pytest.mark.asyncio
async def test_local_runtime_requires_desktop_token() -> None:
    token = os.environ.get("LOCAL_DESKTOP_INSTANCE_TOKEN")
    if token is None:
        from local_project.settings import get_settings

        token = get_settings().desktop_instance_token
    transport = httpx.ASGITransport(app=local_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        denied = await client.get("/internal/v1/ready")
        assert denied.status_code == 401
        assert denied.json()["error"]["code"] == "unauthenticated"
        allowed = await client.get(
            "/internal/v1/ready", headers={"Authorization": f"Bearer {token}"}
        )
        assert allowed.status_code == 200
