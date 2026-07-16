"""Stateful Mil orchestration with durable approvals and verification."""

from dataclasses import dataclass
from pathlib import Path

from mllminal.agent.provider import DeterministicMilProvider, MilProvider, MilRequest
from mllminal.contracts import (
    Approval,
    ApprovalStatus,
    MessageRole,
    PermissionGrant,
    Plan,
    Task,
    TaskState,
    ToolExecution,
    VerificationResult,
)
from mllminal.runtime_store import RuntimeStore
from mllminal.tools import ToolRegistry


@dataclass(frozen=True)
class PendingTask:
    task: Task
    plan: Plan
    approval: Approval


class MilRuntime:
    def __init__(
        self,
        store: RuntimeStore,
        provider: MilProvider | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.store = store
        self.provider = provider or DeterministicMilProvider()
        self.tools = tools or ToolRegistry()

    async def submit(self, session_id: str, request: str, idempotency_key: str) -> PendingTask:
        existing = self.store.find_task_by_idempotency(session_id, idempotency_key)
        if existing is not None:
            return PendingTask(
                task=existing,
                plan=self.store.get_plan_for_task(existing.id),
                approval=self.store.list_approvals(existing.id)[0],
            )
        session = self.store.get_session(session_id)
        self.store.add_message(session_id, MessageRole.USER, request, idempotency_key)
        task, _ = self.store.create_task_idempotent(
            session_id,
            "Inspect project",
            "Inspect the attached project safely",
            idempotency_key,
        )
        task = self.store.transition_task(task.id, TaskState.PLANNING)
        provider_request = MilRequest(
            session_id=session_id,
            task_id=task.id,
            user_message=request,
            workspace_root=session.workspace_root,
            conversation=self.store.list_messages(session_id)[-20:],
            available_tools=list(self.tools.definitions.values()),
            permissions=[
                PermissionGrant(permission="filesystem.read", workspace_root=session.workspace_root)
            ],
        )
        response_text = ""
        plan: Plan | None = None
        async for event in self.provider.stream_response(provider_request):
            if event.event_type == "response.delta" and event.text is not None:
                response_text += event.text
            if event.event_type == "plan.proposed":
                plan = event.plan
            if event.event_type == "provider.failed":
                return PendingTask(
                    task=self.store.transition_task(
                        task.id, TaskState.FAILED, blocker="provider_failed"
                    ),
                    plan=Plan(task_id=task.id, steps=[]),
                    approval=Approval(task_id=task.id, proposal_id="provider_failed"),
                )
        if plan is None:
            raise ValueError("Provider completed without a validated plan")
        self.store.save_plan(plan)
        self.store.add_message(
            session_id,
            MessageRole.MIL,
            response_text,
            idempotency_key=f"mil:{task.id}",
        )
        approval = self.store.create_approval(
            Approval(task_id=task.id, proposal_id=plan.steps[0].proposal.id)
        )
        task = self.store.transition_task(task.id, TaskState.WAITING_FOR_APPROVAL)
        return PendingTask(task=task, plan=plan, approval=approval)

    def decide(self, approval_id: str, status: ApprovalStatus, idempotency_key: str) -> Task:
        approval, changed = self.store.decide_approval(approval_id, status, idempotency_key)
        task = self.store.get_task(approval.task_id)
        if not changed:
            return task
        if status is ApprovalStatus.REJECTED:
            return self.store.transition_task(
                task.id, TaskState.BLOCKED, blocker="approval_rejected"
            )
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
        if not verification.succeeded:
            return self.store.transition_task(
                task.id, TaskState.FAILED, blocker="verification_failed"
            )
        return self.store.transition_task(task.id, TaskState.COMPLETED)
