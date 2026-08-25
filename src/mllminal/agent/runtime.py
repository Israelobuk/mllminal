"""Stateful Mil orchestration with durable approvals and verification."""

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mllminal.agent.latency import LatencyTrace
from mllminal.agent.prompts import PROMPT_VERSION
from mllminal.agent.provider import (
    DeterministicMilProvider,
    MilProvider,
    MilRequest,
    build_bounded_context,
)
from mllminal.agent.routing import MilRoute, route_request
from mllminal.contracts import (
    Approval,
    ApprovalStatus,
    MessageRole,
    PermissionGrant,
    Plan,
    ProviderResponseMetadata,
    Task,
    TaskState,
    ToolExecution,
    VerificationResult,
)
from mllminal.learning.runtime_advisory import LearningRuntimeAdvisor
from mllminal.runtime_store import RuntimeStore
from mllminal.tools import ToolRegistry


@dataclass(frozen=True)
class PendingTask:
    task: Task
    plan: Plan
    approval: Approval


@dataclass(frozen=True)
class ChatResponse:
    response: str
    cached: bool
    route: MilRoute


_SAFE_ROUTES = frozenset({MilRoute.CHAT, MilRoute.LOCAL_INFORMATION, MilRoute.READ_ONLY_TOOL})


class ProviderFailure(RuntimeError):
    """A provider failed without producing an executable plan."""

    def __init__(self, task: Task, category: str, message: str) -> None:
        super().__init__(message)
        self.task = task
        self.category = category


class MilRuntime:
    def __init__(
        self,
        store: RuntimeStore,
        provider: MilProvider | None = None,
        tools: ToolRegistry | None = None,
        advisor: LearningRuntimeAdvisor | None = None,
    ) -> None:
        self.store = store
        self.provider = provider or DeterministicMilProvider()
        self.tools = tools or ToolRegistry()
        self.advisor = advisor
        self._last_latency: dict[str, Any] = {}

    def last_latency(self) -> dict[str, Any]:
        """Return the most recent request trace for diagnostics and benchmarks."""
        return dict(self._last_latency)

    @staticmethod
    def route_request(request: str) -> MilRoute:
        return route_request(request)

    @classmethod
    def is_fast_path_request(cls, request: str) -> bool:
        return cls.route_request(request) in _SAFE_ROUTES

    async def respond(
        self,
        session_id: str,
        request: str,
        idempotency_key: str,
        event_sink: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> ChatResponse:
        """Answer context-free conversation without creating a task or approval."""
        _provider_name, model = self._provider_identity()
        trace = LatencyTrace(route="unknown", model=model, history_size=0, tool_count=0)
        trace.mark("input_received")
        session = self.store.get_session(session_id)
        self.store.add_message(session_id, MessageRole.USER, request, idempotency_key)
        route = self.route_request(request)
        trace.route = route.value
        trace.mark("routing_complete")
        if route not in _SAFE_ROUTES:
            raise ValueError(f"route {route.value} requires the approval-aware task path")

        conversation, was_trimmed = build_bounded_context(
            self.store.list_messages(session_id, limit=21), 20
        )
        trace.history_size = len(conversation)
        trace.mark("context_ready")
        if was_trimmed:
            self.store.append_event(
                session_id, "context.trimmed", {"kept_messages": len(conversation)}
            )

        tool_results: list[dict[str, Any]] = []
        if route is MilRoute.READ_ONLY_TOOL:
            tool_name, arguments = self._read_only_tool(request)
            await self._emit_chat_event(
                session_id,
                "progress",
                text="Checking the requested local information...",
                detail={"route": route.value},
                event_sink=event_sink,
            )
            output = self.tools.execute(tool_name, arguments, Path(session.workspace_root))
            checked = self.tools.verify(tool_name, output)
            tool_results.append(
                {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "output": output,
                    "verified": checked.succeeded,
                }
            )
            await self._emit_chat_event(
                session_id,
                "read_only.completed",
                detail={"tool_name": tool_name, "verified": checked.succeeded},
                event_sink=event_sink,
            )
        trace.tool_count = len(tool_results)

        provider_request = MilRequest(
            session_id=session_id,
            task_id=None,
            user_message=request,
            workspace_root=session.workspace_root,
            conversation=conversation,
            tool_results=tool_results,
            runtime_context=(
                self._local_runtime_context(session.workspace_root)
                if route is MilRoute.LOCAL_INFORMATION
                else {}
            ),
        )
        response_text = ""
        trace.warm = self._provider_warm()
        trace.mark("ollama_request_started")
        async for event in self.provider.stream_conversation(provider_request):
            await self._emit_chat_event(
                session_id,
                event.event_type,
                text=event.text,
                detail=event.detail,
                event_sink=event_sink,
            )
            if event.event_type == "response.delta" and event.text is not None:
                if "first_token_received" not in trace.marks:
                    trace.mark("first_token_received")
                response_text += event.text
            if event.event_type == "provider.failed":
                raise RuntimeError(event.text or "Mil conversational provider failed")
        if not response_text:
            raise RuntimeError("Mil provider completed without a conversational response")
        trace.mark("response_complete")
        await self._record_latency(session_id, trace, event_sink)
        self.store.add_message(
            session_id,
            MessageRole.MIL,
            response_text,
            idempotency_key=f"mil:chat:{idempotency_key}",
        )
        return ChatResponse(response=response_text, cached=False, route=route)

    async def _emit_chat_event(
        self,
        session_id: str,
        event_type: str,
        *,
        text: str | None = None,
        detail: dict[str, Any] | None = None,
        event_sink: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> None:
        event = self.store.append_event(
            session_id,
            event_type,
            {"event_type": event_type, "text": text, "detail": detail or {}},
        )
        if event_sink is not None:
            await event_sink(event.model_dump(mode="json"))

    async def _record_latency(
        self,
        session_id: str,
        trace: LatencyTrace,
        event_sink: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> None:
        self._last_latency = trace.to_dict()
        await self._emit_chat_event(
            session_id,
            "latency.completed",
            detail=self._last_latency,
            event_sink=event_sink,
        )

    def _local_runtime_context(self, workspace_root: str | None) -> dict[str, Any]:
        provider, model = self._provider_identity()
        endpoint = str(getattr(getattr(self.provider, "_client", None), "base_url", "local"))
        return {
            "daemon": "online",
            "provider": provider,
            "model": model,
            "endpoint": endpoint,
            "workspace_root": workspace_root,
            "open_applications": {"available": False, "items": None},
        }

    def _provider_warm(self) -> bool | None:
        warm = getattr(getattr(self.provider, "_client", None), "warm", None)
        return warm if isinstance(warm, bool) else None

    def _provider_identity(self) -> tuple[str, str]:
        if isinstance(self.provider, DeterministicMilProvider):
            return "deterministic", "fixture"
        return "qwen", str(getattr(getattr(self.provider, "_client", None), "model", "unknown"))

    @staticmethod
    def _read_only_tool(request: str) -> tuple[str, dict[str, Any]]:
        match = re.search(r"\b(?:read|show)\s+([A-Za-z0-9_./\\-]+)", request)
        if match is not None and "." in match.group(1):
            return "project.read_text", {"path": match.group(1).replace("\\", "/")}
        if any(term in request.casefold().split() for term in ("list", "files", "folder")):
            return "project.list_files", {"path": "."}
        return "project.inspect_metadata", {}

    async def submit(
        self,
        session_id: str,
        request: str,
        idempotency_key: str,
        event_sink: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> PendingTask:
        existing = self.store.find_task_by_idempotency(session_id, idempotency_key)
        if existing is not None:
            try:
                existing_plan = self.store.get_plan_for_task(existing.id)
                existing_approval = self.store.list_approvals(existing.id)[0]
            except (KeyError, IndexError):
                if existing.state is not TaskState.PLANNING:
                    raise
            else:
                return PendingTask(task=existing, plan=existing_plan, approval=existing_approval)
        session = self.store.get_session(session_id)
        self.store.add_message(session_id, MessageRole.USER, request, idempotency_key)
        task, _ = self.store.create_task_idempotent(
            session_id,
            "Inspect project",
            "Inspect the attached project safely",
            idempotency_key,
        )
        if task.state is not TaskState.PLANNING:
            task = self.store.transition_task(task.id, TaskState.PLANNING)
        conversation, was_trimmed = build_bounded_context(
            self.store.list_messages(session_id, limit=21), 20
        )
        if was_trimmed:
            self.store.append_event(
                session_id, "context.trimmed", {"kept_messages": len(conversation)}
            )
        provider_request = MilRequest(
            session_id=session_id,
            task_id=task.id,
            user_message=request,
            workspace_root=session.workspace_root,
            conversation=conversation,
            available_tools=list(self.tools.definitions.values()),
            permissions=[
                PermissionGrant(permission="filesystem.read", workspace_root=session.workspace_root)
            ],
        )
        response_text = ""
        plan: Plan | None = None
        detail: dict[str, Any] = {}
        async for event in self.provider.stream_response(provider_request):
            envelope = self.store.append_event(
                session_id, event.event_type, event.model_dump(mode="json")
            )
            if event_sink is not None:
                await event_sink(envelope.model_dump(mode="json"))
            if event.event_type == "response.delta" and event.text is not None:
                response_text += event.text
            if event.event_type == "plan.proposed":
                plan = event.plan
                detail = event.detail
            if event.event_type == "provider.failed":
                category = str(event.detail.get("category", "provider_failed"))
                failed = self.store.transition_task(task.id, TaskState.FAILED, blocker=category)
                self._save_metadata(failed, "failed", False, event.detail, category)
                raise ProviderFailure(failed, category, event.text or "Mil provider failed")
        if plan is None:
            failed = self.store.transition_task(task.id, TaskState.FAILED, blocker="missing_plan")
            self._save_metadata(failed, "failed", False, detail, "missing_plan")
            raise ProviderFailure(
                failed, "missing_plan", "Provider completed without a validated plan"
            )
        self._save_metadata(task, "completed", True, detail, None)
        self.store.save_plan(plan)
        self.store.add_message(
            session_id,
            MessageRole.MIL,
            response_text,
            idempotency_key=f"mil:{task.id}",
        )
        if self.advisor is not None:
            self.advisor.recommend(task.id)
        approval = self.store.create_approval(
            Approval(task_id=task.id, proposal_id=plan.steps[0].proposal.id)
        )
        task = self.store.transition_task(task.id, TaskState.WAITING_FOR_APPROVAL)
        return PendingTask(task=task, plan=plan, approval=approval)

    def _save_metadata(
        self,
        task: Task,
        completion_status: str,
        validation_succeeded: bool,
        detail: dict[str, Any],
        failure_category: str | None,
    ) -> None:
        provider = (
            "deterministic" if isinstance(self.provider, DeterministicMilProvider) else "qwen"
        )
        model = (
            "fixture"
            if provider == "deterministic"
            else str(getattr(getattr(self.provider, "_client", None), "model", "unknown"))
        )
        self.store.save_provider_metadata(
            ProviderResponseMetadata(
                task_id=task.id,
                provider=provider,
                model=model,
                prompt_version=PROMPT_VERSION,
                completion_status=completion_status,
                validation_succeeded=validation_succeeded,
                retry_count=int(detail.get("retry_count", 0)),
                failure_category=failure_category,
                input_tokens=detail.get("input_tokens"),
                output_tokens=detail.get("output_tokens"),
            )
        )

    def decide(self, approval_id: str, status: ApprovalStatus, idempotency_key: str) -> Task:
        approval, changed = self.store.decide_approval(approval_id, status, idempotency_key)
        task = self.store.get_task(approval.task_id)
        if not changed:
            return task
        if status is ApprovalStatus.REJECTED:
            blocked = self.store.transition_task(
                task.id, TaskState.BLOCKED, blocker="approval_rejected"
            )
            if self.advisor is not None:
                self.advisor.finalize(task.id, verified=False, completed=False, corrected=True)
            return blocked
        task = self.store.transition_task(task.id, TaskState.EXECUTING)
        plan = self.store.get_plan_for_task(task.id)
        proposal = next(
            step.proposal for step in plan.steps if step.proposal.id == approval.proposal_id
        )
        session = self.store.get_session(task.session_id)
        try:
            output = self.tools.execute(
                proposal.tool_name, proposal.arguments, Path(session.workspace_root)
            )
            execution = self.store.save_execution(
                ToolExecution(
                    task_id=task.id,
                    proposal_id=proposal.id,
                    tool_name=proposal.tool_name,
                    succeeded=True,
                    output=output,
                )
            )
        except Exception as error:
            self.store.save_execution(
                ToolExecution(
                    task_id=task.id,
                    proposal_id=proposal.id,
                    tool_name=proposal.tool_name,
                    succeeded=False,
                    output={},
                    error=str(error),
                )
            )
            return self.store.transition_task(task.id, TaskState.FAILED, blocker=str(error))
        task = self.store.transition_task(task.id, TaskState.VERIFYING)
        checked = self.tools.verify(proposal.tool_name, output)
        verification = self.store.save_verification(
            VerificationResult(
                task_id=task.id,
                execution_id=execution.id,
                succeeded=checked.succeeded,
                detail=checked.detail,
            )
        )
        self.store.add_message(
            task.session_id,
            MessageRole.MIL,
            "Verified tool result: " + json.dumps(execution.output, sort_keys=True),
            idempotency_key=f"verified:{execution.id}",
        )
        if not verification.succeeded:
            failed = self.store.transition_task(
                task.id, TaskState.FAILED, blocker="verification_failed"
            )
            if self.advisor is not None:
                self.advisor.finalize(task.id, verified=False, completed=True)
            return failed
        completed = self.store.transition_task(task.id, TaskState.COMPLETED)
        if self.advisor is not None:
            self.advisor.finalize(task.id, verified=True, completed=True)
        return completed
