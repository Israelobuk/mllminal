"""Authenticated REST and replayable WebSocket API."""

import asyncio
import json
import secrets
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from mllminal.actions.contracts import ActionRequest
from mllminal.actions.service import BoundedActionService
from mllminal.activity.contracts import ActivityRefreshRequest
from mllminal.activity.service import ActivityService
from mllminal.agent.factory import create_provider
from mllminal.agent.runtime import MilRuntime, PendingTask, ProviderFailure
from mllminal.apps.contracts import CapabilityRequest, CapabilityResult
from mllminal.apps.service import ApplicationBridgeService
from mllminal.assistance.contracts import AssistanceRequest
from mllminal.assistance.service import ProactiveAssistanceService
from mllminal.automl.contracts import AutoMLRequest
from mllminal.automl.service import LocalAutoMLService
from mllminal.config import ProviderConfigStore, Settings
from mllminal.contracts import ApprovalStatus, ErrorEnvelope, EventEnvelope, PermissionGrant
from mllminal.demonstration.bridge import DeviceDemonstrationBridge
from mllminal.demonstration.contracts import (
    DemonstrationCaptureRequest,
    DemonstrationStartRequest,
    DemonstrationVariableRequest,
)
from mllminal.demonstration.service import DemonstrationService
from mllminal.device.observer import DeviceObserver
from mllminal.device.windows_adapters import create_native_windows_adapters
from mllminal.device.windows_runtime import WindowsObservationRuntime
from mllminal.interaction.contracts import InteractionEvent
from mllminal.interaction.service import InteractionService
from mllminal.langgraph.adapter import LangGraphWorkflowAdapter
from mllminal.learning.evaluation import EvaluationCase
from mllminal.learning.governance import CandidateGovernanceService, PromotionApprovalError
from mllminal.learning.registry import PolicyRegistry
from mllminal.learning.replay import LearningRepository
from mllminal.learning.runtime_advisory import LearningRuntimeAdvisor
from mllminal.learning.service import CandidateTrainingService, MinimumExperienceError
from mllminal.mining.contracts import MiningRequest
from mllminal.mining.service import WorkflowMiningService
from mllminal.privacy.contracts import (
    CaptureRequest,
    DeletionRequest,
    HistoryExportRequest,
    PrivacyPolicy,
    PrivacyRule,
)
from mllminal.privacy.service import PrivacyService
from mllminal.runtime_store import RuntimeStore
from mllminal.verification.contracts import LocalVisualObservation, VisualVerificationRequest
from mllminal.verification.service import LocalVisualVerificationService
from mllminal.workflow.contracts import (
    WorkflowApprovalRequest,
    WorkflowCreateRequest,
    WorkflowRunRequest,
)
from mllminal.workflow.service import WorkflowService


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
    learning_repository = LearningRepository(settings.database_path)
    learning_repository.initialize()
    runtime = MilRuntime(
        store,
        provider=create_provider(provider_config),
        advisor=LearningRuntimeAdvisor(
            learning_repository, settings.data_dir / "learning" / "checkpoints"
        ),
    )
    privacy = PrivacyService(settings.database_path)

    def native_emergency_stop() -> None:
        privacy.emergency_stop(idempotency_key="native-emergency-stop")

    device_observer = DeviceObserver(
        settings.data_dir / "device",
        create_native_windows_adapters(emergency_stop=native_emergency_stop),
    )
    device_runtime = WindowsObservationRuntime(
        device_observer,
        emergency_stop_active=lambda: privacy.status().emergency_stop_active,
    )
    interaction = InteractionService(settings.database_path, privacy)
    activity = ActivityService(settings.database_path, interaction, device_observer)
    workflow = WorkflowService(settings.database_path)
    applications = ApplicationBridgeService(
        settings.database_path,
        workspace_root=settings.workspace_root,
        emergency_stop_active=lambda: privacy.status().emergency_stop_active,
    )
    visual = LocalVisualVerificationService(settings.data_dir / "visual")
    mining = WorkflowMiningService()
    actions = BoundedActionService(
        emergency_stop_active=lambda: privacy.status().emergency_stop_active
    )
    langgraph = LangGraphWorkflowAdapter()
    automl = LocalAutoMLService()
    assistance = ProactiveAssistanceService()
    demonstration = DemonstrationService(settings.database_path, interaction)
    demonstration_bridge = DeviceDemonstrationBridge(demonstration)
    device_observer.subscribe(demonstration_bridge.handle)
    hub = EventHub()
    app = FastAPI(title="mllminald", version="0.1.0")
    app.state.shutdown_callback = None
    app.state.runtime = runtime
    app.state.provider_config = provider_config
    app.state.learning_repository = learning_repository
    app.state.device_observer = device_observer
    app.state.device_runtime = device_runtime
    app.router.add_event_handler("shutdown", device_runtime.stop)
    app.state.privacy = privacy
    app.state.interaction = interaction
    app.state.activity = activity
    app.state.workflow = workflow
    app.state.applications = applications
    app.state.visual = visual
    app.state.mining = mining
    app.state.actions = actions
    app.state.langgraph = langgraph
    app.state.automl = automl
    app.state.assistance = assistance
    app.state.demonstration = demonstration
    app.state.demonstration_bridge = demonstration_bridge

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

    @app.get("/v1/privacy/status", dependencies=protected)
    async def privacy_status() -> dict[str, Any]:
        return privacy.status().model_dump(mode="json")

    @app.get("/v1/privacy/policy", dependencies=protected)
    async def privacy_policy() -> dict[str, Any]:
        return privacy.policy().model_dump(mode="json")

    @app.put("/v1/privacy/policy", dependencies=protected)
    async def update_privacy_policy(
        body: PrivacyPolicy,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return privacy.update_policy(body, idempotency_key=idempotency_key).model_dump(mode="json")

    @app.post("/v1/privacy/enable", dependencies=protected)
    async def privacy_enable(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        result = privacy.enable(idempotency_key=idempotency_key)
        device_runtime.start()
        return result.model_dump(mode="json")

    @app.post("/v1/privacy/disable", dependencies=protected)
    async def privacy_disable(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        result = privacy.disable(idempotency_key=idempotency_key)
        device_runtime.stop()
        return result.model_dump(mode="json")

    @app.post("/v1/privacy/pause", dependencies=protected)
    async def privacy_pause(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        result = privacy.pause(idempotency_key=idempotency_key)
        device_runtime.pause()
        return result.model_dump(mode="json")

    @app.post("/v1/privacy/resume", dependencies=protected)
    async def privacy_resume(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        result = privacy.resume(idempotency_key=idempotency_key)
        device_runtime.resume()
        return result.model_dump(mode="json")

    @app.post("/v1/privacy/incognito/start", dependencies=protected)
    async def privacy_incognito_start(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return privacy.start_incognito(idempotency_key=idempotency_key).model_dump(mode="json")

    @app.post("/v1/privacy/incognito/stop", dependencies=protected)
    async def privacy_incognito_stop(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return privacy.stop_incognito(idempotency_key=idempotency_key).model_dump(mode="json")

    @app.post("/v1/privacy/emergency-stop", dependencies=protected)
    async def privacy_emergency_stop(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        result = privacy.emergency_stop(idempotency_key=idempotency_key)
        device_runtime.emergency_stop()
        return result.model_dump(mode="json")

    @app.post("/v1/privacy/emergency-clear", dependencies=protected)
    async def privacy_emergency_clear(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return privacy.emergency_clear(idempotency_key=idempotency_key).model_dump(mode="json")

    @app.get("/v1/privacy/exclusions", dependencies=protected)
    async def privacy_exclusions() -> list[dict[str, Any]]:
        return [rule.model_dump(mode="json") for rule in privacy.exclusions()]

    @app.post("/v1/privacy/exclusions", dependencies=protected)
    async def add_privacy_exclusion(
        body: PrivacyRule,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return privacy.add_exclusion(body, idempotency_key=idempotency_key).model_dump(mode="json")

    @app.delete("/v1/privacy/exclusions/{rule_id}", dependencies=protected)
    async def remove_privacy_exclusion(
        rule_id: str,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, bool]:
        return {"deleted": privacy.remove_exclusion(rule_id, idempotency_key=idempotency_key)}

    @app.post("/v1/privacy/capture", dependencies=protected)
    async def privacy_capture(
        body: CaptureRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return privacy.capture(body, idempotency_key=idempotency_key).model_dump(mode="json")

    @app.get("/v1/privacy/history", dependencies=protected)
    async def privacy_history() -> list[dict[str, Any]]:
        return [record.model_dump(mode="json") for record in privacy.history()]

    @app.post("/v1/privacy/history/export", dependencies=protected)
    async def export_privacy_history(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        body: HistoryExportRequest | None = None,
    ) -> dict[str, Any]:
        return {"history": json.loads(privacy.export_history(before=body.before if body else None))}

    @app.post("/v1/privacy/history/delete", dependencies=protected)
    async def delete_privacy_history(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        body: DeletionRequest | None = None,
    ) -> dict[str, int]:
        return {
            "deleted": privacy.delete_history(
                idempotency_key=idempotency_key, before=body.before if body else None
            )
        }

    @app.get("/v1/interaction/status", dependencies=protected)
    async def interaction_status() -> dict[str, Any]:
        return interaction.status().model_dump(mode="json")

    @app.post("/v1/interaction/events", dependencies=protected)
    async def capture_interaction(
        body: InteractionEvent,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return interaction.capture(body, idempotency_key=idempotency_key).model_dump(mode="json")

    @app.get("/v1/interaction/events", dependencies=protected)
    async def interaction_events() -> list[dict[str, Any]]:
        return [event.model_dump(mode="json") for event in interaction.events()]

    @app.post("/v1/interaction/replay/authorize", dependencies=protected)
    async def authorize_interaction_replay(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return interaction.authorize_replay(idempotency_key=idempotency_key).model_dump(mode="json")

    @app.post("/v1/interaction/replay/revoke", dependencies=protected)
    async def revoke_interaction_replay(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return interaction.revoke_replay(idempotency_key=idempotency_key).model_dump(mode="json")

    @app.post("/v1/interaction/events/{event_id}/replay", dependencies=protected)
    async def prepare_interaction_replay(
        event_id: str,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return interaction.prepare_replay(event_id, idempotency_key=idempotency_key).model_dump(
            mode="json"
        )

    @app.get("/v1/demonstrate/status", dependencies=protected)
    async def demonstration_status(session_id: str | None = None) -> dict[str, Any]:
        return demonstration.status(session_id).model_dump(mode="json")

    @app.post("/v1/demonstrate/start", dependencies=protected)
    async def demonstration_start(
        body: DemonstrationStartRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        if not privacy.status().observation_enabled:
            raise PermissionError("Enable visible observation before starting a demonstration")
        return demonstration.start(
            body.label,
            timeout_seconds=body.timeout_seconds,
            emergency_stop_shortcut=body.emergency_stop_shortcut,
            idempotency_key=idempotency_key,
        ).model_dump(mode="json")

    @app.get("/v1/demonstrate/sessions", dependencies=protected)
    async def demonstration_sessions() -> list[dict[str, Any]]:
        return [session.model_dump(mode="json") for session in demonstration.sessions()]

    @app.post("/v1/demonstrate/sessions/{session_id}/record", dependencies=protected)
    async def demonstration_record(
        session_id: str,
        body: DemonstrationCaptureRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return demonstration.record(session_id, body, idempotency_key=idempotency_key).model_dump(
            mode="json"
        )

    @app.post("/v1/demonstrate/sessions/{session_id}/stop", dependencies=protected)
    async def demonstration_stop(
        session_id: str,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return demonstration.stop(session_id, idempotency_key=idempotency_key).model_dump(
            mode="json"
        )

    @app.post("/v1/demonstrate/sessions/{session_id}/cancel", dependencies=protected)
    async def demonstration_cancel(
        session_id: str,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return demonstration.cancel(session_id, idempotency_key=idempotency_key).model_dump(
            mode="json"
        )

    @app.post("/v1/demonstrate/sessions/{session_id}/emergency-stop", dependencies=protected)
    async def demonstration_emergency_stop(
        session_id: str,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return demonstration.emergency_stop(session_id, idempotency_key=idempotency_key).model_dump(
            mode="json"
        )

    @app.get("/v1/demonstrate/sessions/{session_id}/steps", dependencies=protected)
    async def demonstration_steps(session_id: str) -> list[dict[str, Any]]:
        return [step.model_dump(mode="json") for step in demonstration.steps(session_id)]

    @app.post("/v1/demonstrate/sessions/{session_id}/variables", dependencies=protected)
    async def demonstration_variable(
        session_id: str,
        body: DemonstrationVariableRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return demonstration.assign_variable(
            session_id,
            body.event_id,
            body.label,
            field_name=body.field_name,
            idempotency_key=idempotency_key,
        ).model_dump(mode="json")

    @app.get("/v1/demonstrate/candidates/{candidate_id}", dependencies=protected)
    async def demonstration_candidate(candidate_id: str) -> dict[str, Any]:
        return demonstration.candidate(candidate_id).model_dump(mode="json")

    @app.get("/v1/activity/summary", dependencies=protected)
    async def activity_summary() -> dict[str, Any]:
        summary = activity.summary()
        return summary.model_dump(mode="json") if summary else {}

    @app.post("/v1/activity/refresh", dependencies=protected)
    async def activity_refresh(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        body: ActivityRefreshRequest | None = None,
    ) -> dict[str, Any]:
        return activity.refresh(
            lookback_minutes=body.lookback_minutes if body else 1440,
            idempotency_key=idempotency_key,
        ).model_dump(mode="json")

    @app.get("/v1/activity/segments", dependencies=protected)
    async def activity_segments() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in activity.segments()]

    @app.get("/v1/activity/applications", dependencies=protected)
    async def activity_applications() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in activity.application_sessions()]

    @app.get("/v1/activity/tasks", dependencies=protected)
    async def activity_tasks() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in activity.task_sessions()]

    @app.get("/v1/activity/context-switches", dependencies=protected)
    async def activity_context_switches() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in activity.context_switches()]

    @app.get("/v1/activity/boundaries", dependencies=protected)
    async def activity_boundaries() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in activity.task_boundaries()]

    @app.get("/v1/workflows", dependencies=protected)
    async def workflow_definitions() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in workflow.definitions()]

    @app.post("/v1/workflows", dependencies=protected)
    async def workflow_create(
        body: WorkflowCreateRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return workflow.create(body.definition, idempotency_key=idempotency_key).model_dump(
            mode="json"
        )

    @app.get("/v1/workflows/{workflow_id}", dependencies=protected)
    async def workflow_definition(workflow_id: str) -> dict[str, Any]:
        return workflow.definition(workflow_id).model_dump(mode="json")

    @app.post("/v1/workflows/{workflow_id}/activate", dependencies=protected)
    async def workflow_activate(
        workflow_id: str,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return workflow.activate(workflow_id, idempotency_key=idempotency_key).model_dump(
            mode="json"
        )

    @app.post("/v1/workflows/{workflow_id}/archive", dependencies=protected)
    async def workflow_archive(
        workflow_id: str,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return workflow.archive(workflow_id, idempotency_key=idempotency_key).model_dump(
            mode="json"
        )

    @app.post("/v1/workflows/{workflow_id}/runs", dependencies=protected)
    async def workflow_run(
        workflow_id: str,
        body: WorkflowRunRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return workflow.run(workflow_id, body, idempotency_key=idempotency_key).model_dump(
            mode="json"
        )

    @app.get("/v1/workflow-runs", dependencies=protected)
    async def workflow_runs() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in workflow.runs()]

    @app.get("/v1/workflow-runs/{run_id}", dependencies=protected)
    async def workflow_run_record(run_id: str) -> dict[str, Any]:
        return workflow.run_record(run_id).model_dump(mode="json")

    @app.post("/v1/workflow-runs/{run_id}/approve", dependencies=protected)
    async def workflow_approve(
        run_id: str,
        body: WorkflowApprovalRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return workflow.approve(run_id, body.approved, idempotency_key=idempotency_key).model_dump(
            mode="json"
        )

    @app.post("/v1/workflow-runs/{run_id}/rollback", dependencies=protected)
    async def workflow_rollback(
        run_id: str,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return workflow.rollback(run_id, idempotency_key=idempotency_key).model_dump(mode="json")

    @app.get("/v1/workflow-runs/{run_id}/events", dependencies=protected)
    async def workflow_events(run_id: str) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in workflow.events(run_id)]

    @app.get("/v1/apps", dependencies=protected)
    async def application_discovery() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in await applications.discover()]

    @app.get("/v1/apps/grants", dependencies=protected)
    async def application_grants() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in applications.grants()]

    @app.get("/v1/apps/{application}/capabilities", dependencies=protected)
    async def application_capabilities(application: str) -> list[dict[str, Any]]:
        return [
            item.model_dump(mode="json") for item in await applications.capabilities(application)
        ]

    @app.post("/v1/apps/{application}/grant", dependencies=protected)
    async def application_grant(
        application: str,
        scope: str,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return applications.grant(application, scope, idempotency_key=idempotency_key).model_dump(
            mode="json"
        )

    @app.post("/v1/apps/{application}/execute", dependencies=protected)
    async def application_execute(
        application: str,
        body: CapabilityRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return (
            await applications.execute(application, body, idempotency_key=idempotency_key)
        ).model_dump(mode="json")

    @app.post("/v1/apps/{application}/verify", dependencies=protected)
    async def application_verify(
        application: str,
        body: CapabilityResult,
    ) -> dict[str, Any]:
        return (await applications.verify(application, body)).model_dump(mode="json")

    @app.post("/v1/visual/observe", dependencies=protected)
    async def visual_observe(body: LocalVisualObservation) -> dict[str, Any]:
        return visual.observe(body).model_dump(mode="json")

    @app.get("/v1/visual/latest", dependencies=protected)
    async def visual_latest() -> dict[str, Any] | None:
        latest = visual.latest()
        return latest.model_dump(mode="json") if latest is not None else None

    @app.post("/v1/visual/verify", dependencies=protected)
    async def visual_verify(body: VisualVerificationRequest) -> dict[str, Any]:
        return visual.verify(body).model_dump(mode="json")

    @app.post("/v1/workflow-mining", dependencies=protected)
    async def workflow_mining(body: MiningRequest) -> dict[str, Any]:
        return mining.mine(interaction.events(), body).model_dump(mode="json")

    @app.get("/v1/actions", dependencies=protected)
    async def action_catalog() -> list[str]:
        return actions.actions()

    @app.post("/v1/actions/execute", dependencies=protected)
    async def action_execute(
        body: ActionRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return actions.execute(body, idempotency_key=idempotency_key).model_dump(mode="json")

    @app.post("/v1/assistance/suggest", dependencies=protected)
    async def assistance_suggest(body: AssistanceRequest) -> dict[str, Any]:
        mined = mining.mine(interaction.events(), body.mining)
        return assistance.suggest(mined, body).model_dump(mode="json")

    @app.post("/v1/adapters/langgraph", dependencies=protected)
    async def langgraph_spec(body: WorkflowCreateRequest) -> dict[str, Any]:
        spec = langgraph.spec(body.definition)
        return {"available": langgraph.available(), "spec": spec.model_dump(mode="json")}

    @app.post("/v1/automl/rank", dependencies=protected)
    async def automl_rank(body: AutoMLRequest) -> dict[str, Any]:
        return automl.rank(body).model_dump(mode="json")

    @app.get("/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "daemon": "mllminald"}

    @app.get("/v1/device/status", dependencies=protected)
    async def device_status() -> dict[str, Any]:
        privacy_state = privacy.status()
        current_application = None
        for event in reversed(device_observer.events()):
            if event.application is not None:
                current_application = event.application.process_name
                break
        return {
            "state": device_observer.status.state,
            "observation_enabled": privacy_state.observation_enabled,
            "paused": privacy_state.paused or device_observer.status.state == "PAUSED",
            "dropped_events": device_observer.status.dropped_events,
            "duplicate_events": device_observer.status.duplicate_events,
            "semantic_clicks_enabled": True,
            "shortcut_monitoring_enabled": True,
            "text_metadata_enabled": False,
            "temporary_vision_enabled": False,
            "current_application": current_application,
            "exclusions_active": privacy_state.exclusion_count > 0,
            "emergency_stop_active": privacy_state.emergency_stop_active,
        }

    @app.get("/v1/device/capabilities", dependencies=protected)
    async def device_capabilities() -> list[dict[str, Any]]:
        return [capability.__dict__ for capability in device_observer.capabilities()]

    @app.get("/v1/device/events", dependencies=protected)
    async def device_events() -> list[dict[str, Any]]:
        return [event.model_dump(mode="json") for event in device_observer.events()]

    @app.post("/v1/device/start", dependencies=protected)
    async def device_start() -> dict[str, str]:
        device_runtime.start()
        return {"state": device_observer.status.state}

    @app.post("/v1/device/stop", dependencies=protected)
    async def device_stop() -> dict[str, str]:
        device_runtime.stop()
        return {"state": device_observer.status.state}

    @app.post("/v1/device/pause", dependencies=protected)
    async def device_pause() -> dict[str, str]:
        device_runtime.pause()
        return {"state": device_observer.status.state}

    @app.post("/v1/device/resume", dependencies=protected)
    async def device_resume() -> dict[str, str]:
        device_runtime.resume()
        return {"state": device_observer.status.state}

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

    @app.websocket("/v1/privacy/events/stream")
    async def privacy_event_stream(socket: WebSocket) -> None:
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
            for event in privacy.events(after):
                await socket.send_json(event)
        except (WebSocketDisconnect, TimeoutError, ValueError):
            return

    @app.websocket("/v1/device/events/stream")
    async def device_event_stream(socket: WebSocket) -> None:
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
            while True:
                events = [
                    event for event in device_observer.events() if event.monotonic_sequence > after
                ]
                for event in events:
                    await socket.send_json(event.model_dump(mode="json"))
                    after = event.monotonic_sequence
                await asyncio.sleep(0.1)
        except (WebSocketDisconnect, TimeoutError, ValueError):
            return

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
