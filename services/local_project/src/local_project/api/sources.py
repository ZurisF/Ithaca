from dataclasses import asdict
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from local_project.inventory.walk import inventory
from local_project.observability.trace import trace_sink
from local_project.observer.run import observe
from local_project.observer.tasks import observer_tasks
from local_project.settings import get_settings
from local_project.source_registry.chooser import choose_directory
from local_project.source_registry.registry import registry
from model_adapter import ModelAdapter, OpenAICompatibleAdapter


class AuthorizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    path: str = Field(min_length=1, max_length=4096)


class ObserveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    operation_id: UUID


class ChooseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID


@lru_cache(maxsize=1)
def get_observer_model() -> ModelAdapter:
    settings = get_settings()
    return OpenAICompatibleAdapter(
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        model=settings.model_name,
        provider=settings.model_provider,
        trace_sink=trace_sink,
        max_concurrency=settings.model_max_concurrency,
    )


def make_router(token_dependency) -> APIRouter:
    router = APIRouter(dependencies=[Depends(token_dependency)])

    @router.post("/v1/sources:authorize")
    async def authorize(body: AuthorizeRequest) -> dict[str, str]:
        return {"source_handle": registry.authorize(body.session_id, body.path)}

    @router.post("/v1/sources:choose")
    async def choose(body: ChooseRequest) -> dict[str, object]:
        path = await choose_directory()
        handle = registry.authorize(body.session_id, path)
        try:
            items, partial = inventory(registry.get(handle, body.session_id))
        except BaseException:
            registry.release(handle, body.session_id)
            raise
        return {
            "source_handle": handle,
            "files": [asdict(item) for item in items],
            "partial": partial,
        }

    @router.get("/v1/sources/{source_handle}/inventory")
    async def get_inventory(
        source_handle: str, session_id: Annotated[UUID, Query()]
    ) -> dict[str, object]:
        root = registry.get(source_handle, session_id)
        items, partial = inventory(root)
        return {"files": [asdict(item) for item in items], "partial": partial}

    @router.post("/v1/sources/{source_handle}:observe")
    async def observe_source(
        source_handle: str,
        body: ObserveRequest,
        model: Annotated[ModelAdapter, Depends(get_observer_model)],
    ) -> dict[str, str]:
        root = registry.get(source_handle, body.session_id)
        markdown = await observer_tasks.run(
            body.operation_id,
            body.session_id,
            source_handle,
            lambda: observe(root, body.session_id, model),
        )
        return {"operation_id": str(body.operation_id), "snapshot": markdown}

    @router.delete("/v1/sources/{source_handle}")
    async def release(source_handle: str, session_id: Annotated[UUID, Query()]) -> dict[str, str]:
        registry.release(source_handle, session_id)
        return {"status": "released"}

    return router
