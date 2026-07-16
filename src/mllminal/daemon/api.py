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
from mllminal.learning.evaluation import EvaluationCase
from mllminal.learning.governance import CandidateGovernanceService, PromotionApprovalError
from mllminal.learning.registry import PolicyRegistry
from mllminal.learning.replay import LearningRepository
from mllminal.learning.service import CandidateTrainingService, MinimumExperienceError
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


class PromotionApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explicitly_approved: bool


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
    """Build the daemon API around one configured provider and replayable event store."""
    provider_config = ProviderConfigStore(settings).load()
    runtime = MilRuntime(store, provider=create_provider(provider_config))
    learning_repository = LearningRepository(settings.database_path)
    learning_repository.initialize()
    hub = EventHub()
    app = FastAPI(title="mllminald", version="0.1.0")
    app.state.shutdown_callback = None
    app.state.runtime = runtime
    app.state.provider_config = provider_config
    app.state.learning_repository = learning_repository

    def error_response(
        code: str,
        message: str,
        status_code: int,
        *,
        retryable: bool = False,
        detail: dict[str, Any] | None = None,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content=ErrorEnvelope(
                code=code,
                message=message,
                retryable=retryable,
                detail=detail or {},
            ).model_dump(mode="json"),
        )

    async def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {token}"
        if authorization is None or not secrets.compare_digest(authorization, expected):
            raise PermissionError("Valid bearer token required")

    @app.exception_handler(PermissionError)
    async def permission_handler(_request: Request, exception: PermissionError) -> JSONResponse:
        return error_response("unauthorized", str(exception), 401)

    @app.exception_handler(KeyError)
    async def key_handler(_request: Request, exception: KeyError) -> JSONResponse:
        return error_response("not_found", f"Resource not found: {exception.args[0]}", 404)

    @app.exception_handler(ProviderFailure)
    async def provider_failure_handler(
        _request: Request, exception: ProviderFailure
    ) -> JSONResponse:
        return error_response(
            "provider_failed",
            str(exception),
            503,
            retryable=exception.category in {"timeout", "unavailable", "http_error"},
            detail={"category": exception.category},
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
            return error_response(
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

    @app.get("/v1/learning/status", dependencies=protected)
    async def learning_status() -> dict[str, Any]:
        return learning_repository.get_settings().model_dump(mode="json")

    @app.get("/v1/learning/runs", dependencies=protected)
    async def learning_runs() -> list[dict[str, Any]]:
        return [run.model_dump(mode="json") for run in learning_repository.list_training_runs()]

    @app.get("/v1/learning/policies", dependencies=protected)
    async def learning_policies() -> list[dict[str, Any]]:
        return [
            policy.model_dump(mode="json") for policy in learning_repository.list_policy_versions()
        ]

    @app.post("/v1/learning/train", dependencies=protected)
    async def train_learning_candidate() -> Any:
        try:
            result = CandidateTrainingService(
                learning_repository, settings.data_dir / "learning"
            ).train()
        except MinimumExperienceError as error:
            return error_response("minimum_experience_not_met", str(error), 409, retryable=True)
        return {
            "training_run": result.training_run.model_dump(mode="json"),
            "candidate": result.candidate.model_dump(mode="json"),
            "checkpoint": str(result.checkpoint),
        }

    def governance() -> CandidateGovernanceService:
        return CandidateGovernanceService(
            learning_repository,
            PolicyRegistry(learning_repository, settings.data_dir / "learning" / "checkpoints"),
        )

    @app.post("/v1/learning/evaluate/{policy_name}", dependencies=protected)
    async def evaluate_learning(policy_name: str) -> Any:
        matches = [
            policy
            for policy in learning_repository.list_policy_versions()
            if policy.name == policy_name
        ]
        if len(matches) != 1 or matches[0].training_run_id is None:
            return error_response("invalid_policy", "Candidate policy cannot be evaluated", 422)
        samples = learning_repository.sample_replay(
            learning_repository.count_replay_entries(), seed=learning_repository.get_settings().seed
        )
        if not samples:
            return error_response("no_replay_samples", "No held-out replay samples available", 409)
        result = governance().evaluate(
            matches[0].id,
            matches[0].training_run_id,
            [EvaluationCase(sample=sample, action_mask=(True,) * 9) for sample in samples],
        )
        return result.report.model_dump(mode="json")

    @app.post("/v1/learning/promote/{policy_name}", dependencies=protected)
    async def promote_learning(
        policy_name: str,
        body: PromotionApproval,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> Any:
        matches = [
            policy
            for policy in learning_repository.list_policy_versions()
            if policy.name == policy_name
        ]
        reports = [
            report
            for report in learning_repository.list_evaluation_reports()
            if matches and report.candidate_policy_id == matches[0].id
        ]
        if len(matches) != 1 or not reports:
            return error_response("missing_evaluation", "Candidate has no evaluation report", 409)
        try:
            policy = governance().promote(
                matches[0].id,
                reports[-1].id,
                explicitly_approved=body.explicitly_approved,
                idempotency_key=idempotency_key,
            )
        except PromotionApprovalError as error:
            return error_response("promotion_rejected", str(error), 409)
        return policy.model_dump(mode="json")

    @app.post("/v1/learning/rollback", dependencies=protected)
    async def rollback_learning(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> Any:
        try:
            record = governance().rollback(
                reason="API operator rollback", idempotency_key=idempotency_key
            )
        except KeyError:
            return error_response("rollback_unavailable", "No previous promoted policy", 409)
        return record.model_dump(mode="json")

    @app.get("/v1/learning/compare/{candidate_name}/{current_name}", dependencies=protected)
    async def compare_learning(candidate_name: str, current_name: str) -> dict[str, str]:
        return {"candidate": candidate_name, "current": current_name}

    @app.post("/v1/daemon/shutdown", dependencies=protected)
    async def shutdown() -> dict[str, str]:
        callback = app.state.shutdown_callback
        if callback is not None:
            callback()
        return {"status": "shutting_down"}

    @app.websocket("/v1/learning/events")
    async def learning_events(socket: WebSocket) -> None:
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
            after = int(socket.query_params.get("after_sequence", "0"))
            await socket.send_json({"type": "authenticated"})
            for event in learning_repository.list_events(after):
                await socket.send_json(
                    {
                        "sequence": event.sequence,
                        "event_type": event.event_type,
                        "payload": event.payload,
                        "created_at": event.created_at.isoformat(),
                    }
                )
        except (WebSocketDisconnect, TimeoutError, ValueError):
            return

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
