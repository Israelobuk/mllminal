"""Authenticated REST and replayable WebSocket API."""

import asyncio
import secrets
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from mllminal.agent.factory import create_provider
from mllminal.agent.runtime import MilRuntime, PendingTask, ProviderFailure
from mllminal.config import ProviderConfigStore, Settings
from mllminal.contracts import ApprovalStatus, ErrorEnvelope, EventEnvelope, PermissionGrant
from mllminal.runtime_store import RuntimeStore


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_root: str


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ApprovalStatus


class EventHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[EventEnvelope]]] = defaultdict(set)

    @asynccontextmanager
    async def subscribe(self, session_id: str) -> AsyncIterator[asyncio.Queue[EventEnvelope]]:
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue(maxsize=256)
        self._subscribers[session_id].add(queue)
        try:
            yield queue
        finally:
            self._subscribers[session_id].discard(queue)

    async def publish(self, events: list[EventEnvelope]) -> None:
        for envelope in events:
            for queue in tuple(self._subscribers[envelope.session_id]):
                if queue.full():
                    _ = queue.get_nowait()
                queue.put_nowait(envelope)


def create_app(settings: Settings, store: RuntimeStore, token: str) -> FastAPI:
    provider_config = ProviderConfigStore(settings).load()
    runtime = MilRuntime(store, provider=create_provider(provider_config))
    provider_config = ProviderConfigStore(settings).load()
    hub = EventHub()
    app = FastAPI(title="mllminald", version="0.1.0")
    app.state.shutdown_callback = None

    def error(code: str, message: str, status_code: int) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content=ErrorEnvelope(code=code, message=message).model_dump(mode="json"),
        )

    async def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {token}"
        if authorization is None or not secrets.compare_digest(authorization, expected):
            raise PermissionError("Valid bearer token required")

    @app.exception_handler(PermissionError)
    async def permission_handler(_request: Request, exception: PermissionError) -> JSONResponse:
        return error("unauthorized", str(exception), 401)

    @app.exception_handler(KeyError)
    async def key_handler(_request: Request, exception: KeyError) -> JSONResponse:
        return error("not_found", f"Resource not found: {exception.args[0]}", 404)

    @app.exception_handler(ProviderFailure)
    async def provider_failure_handler(
        _request: Request, exception: ProviderFailure
    ) -> JSONResponse:
        retryable = exception.category in {"timeout", "unavailable", "http_error"}
        return JSONResponse(
            status_code=503,
            content=ErrorEnvelope(
                code="provider_failed",
                message=str(exception),
                retryable=retryable,
                detail={"category": exception.category},
            ).model_dump(mode="json"),
        )

    protected = [Depends(authorize)]

    @app.get("/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "daemon": "mllminald"}

    @app.get("/v1/status", dependencies=protected)
    async def status() -> dict[str, Any]:
        return {
            "product": "MLLminal",
            "daemon": "Online",
            "mil": "Online",
            "provider": provider_config.provider,
            "model": provider_config.model,
            "endpoint": provider_config.base_url,
            "streaming": True,
            "execution_mode": "Approval required",
            "learning": "Deferred",
            "task_count": len(store.list_tasks()),
        }

    @app.post("/v1/sessions", dependencies=protected)
    async def create_session(body: SessionCreate) -> Any:
        workspace = Path(body.workspace_root).resolve()
        if not workspace.is_dir():
            return error(
                "invalid_workspace", "Attached workspace must be an existing directory", 422
            )
        return store.create_session(str(workspace)).model_dump(mode="json")

    @app.get("/v1/sessions/{session_id}", dependencies=protected)
    async def get_session(session_id: str) -> dict[str, Any]:
        session = store.get_session(session_id)
        return {
            **session.model_dump(mode="json"),
            "messages": [item.model_dump(mode="json") for item in store.list_messages(session_id)],
        }

    @app.post("/v1/sessions/{session_id}/messages", dependencies=protected)
    async def create_message(
        session_id: str,
        body: MessageCreate,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        previous = store.list_events(session_id)
        after = previous[-1].sequence if previous else 0
        pending = await runtime.submit(session_id, body.content, idempotency_key)
        await hub.publish(store.list_events(session_id, after))
        return _pending_payload(pending)

    @app.get("/v1/tasks", dependencies=protected)
    async def list_tasks() -> list[dict[str, Any]]:
        return [task.model_dump(mode="json") for task in store.list_tasks()]

    @app.get("/v1/tasks/{task_id}", dependencies=protected)
    async def get_task(task_id: str) -> dict[str, Any]:
        return store.get_task(task_id).model_dump(mode="json")

    @app.post("/v1/approvals/{approval_id}/decisions", dependencies=protected)
    async def decide_approval(
        approval_id: str,
        body: ApprovalDecision,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        approval = store.get_approval(approval_id)
        previous = store.list_events(store.get_task(approval.task_id).session_id)
        after = previous[-1].sequence if previous else 0
        task = runtime.decide(approval_id, body.status, idempotency_key)
        await hub.publish(store.list_events(task.session_id, after))
        return task.model_dump(mode="json")

    @app.get("/v1/permissions", dependencies=protected)
    async def permissions() -> list[dict[str, Any]]:
        grant = PermissionGrant(
            permission="filesystem.read",
            workspace_root=str(settings.workspace_root.resolve()),
        )
        return [grant.model_dump(mode="json")]

    @app.post("/v1/daemon/shutdown", dependencies=protected)
    async def shutdown() -> dict[str, str]:
        callback = app.state.shutdown_callback
        if callback is not None:
            callback()
        return {"status": "shutting_down"}

    @app.websocket("/v1/events")
    async def events(socket: WebSocket) -> None:
        await socket.accept()
        try:
            authentication = await asyncio.wait_for(socket.receive_json(), timeout=5)
            supplied = authentication.get("token") if isinstance(authentication, dict) else None
            if authentication.get("type") != "authenticate" or not isinstance(supplied, str):
                await socket.close(code=4401, reason="Authentication required")
                return
            if not secrets.compare_digest(supplied, token):
                await socket.close(code=4401, reason="Authentication failed")
                return
            session_id = socket.query_params["session_id"]
            after = int(socket.query_params.get("after_sequence", "0"))
            await socket.send_json({"type": "authenticated"})
            for envelope in store.list_events(session_id, after):
                await socket.send_json(envelope.model_dump(mode="json"))
            async with hub.subscribe(session_id) as queue:
                while True:
                    await socket.send_json((await queue.get()).model_dump(mode="json"))
        except (WebSocketDisconnect, TimeoutError, KeyError, ValueError):
            return

    return app


def _pending_payload(pending: PendingTask) -> dict[str, Any]:
    return {
        "task": pending.task.model_dump(mode="json"),
        "plan": pending.plan.model_dump(mode="json"),
        "approval": pending.approval.model_dump(mode="json"),
    }
