"""Persistence extensions for plans, approvals, execution, and verification."""

import json
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Session as DbSession

from mllminal.contracts import (
    Approval,
    ApprovalStatus,
    Plan,
    ProviderResponseMetadata,
    Task,
    ToolExecution,
    VerificationResult,
    utc_now,
)
from mllminal.persistence import Base, Store, TaskRow


class RequestRow(Base):
    __tablename__ = "requests"
    __table_args__ = (UniqueConstraint("session_id", "idempotency_key"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    idempotency_key: Mapped[str]
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)


class PlanRow(Base):
    __tablename__ = "plans"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)
    plan_json: Mapped[str] = mapped_column(Text)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    proposal_id: Mapped[str]
    status: Mapped[str]
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_key: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    created_at: Mapped[datetime]
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ExecutionRow(Base):
    __tablename__ = "executions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    proposal_id: Mapped[str]
    tool_name: Mapped[str]
    succeeded: Mapped[bool]
    output_json: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime]


class VerificationRow(Base):
    __tablename__ = "verifications"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"))
    succeeded: Mapped[bool]
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class ProviderResponseRow(Base):
    __tablename__ = "provider_responses"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)
    metadata_json: Mapped[str] = mapped_column(Text)


class RuntimeStore(Store):
    def create_task_idempotent(
        self, session_id: str, title: str, goal: str, idempotency_key: str
    ) -> tuple[Task, bool]:
        existing = self.find_task_by_idempotency(session_id, idempotency_key)
        if existing is not None:
            return existing, False
        task = self.create_task(session_id, title, goal)
        with self.transaction() as database:
            database.add(
                RequestRow(session_id=session_id, idempotency_key=idempotency_key, task_id=task.id)
            )
        return task, True

    def find_task_by_idempotency(self, session_id: str, idempotency_key: str) -> Task | None:
        with DbSession(self.engine) as database:
            row = database.scalar(
                select(RequestRow).where(
                    RequestRow.session_id == session_id,
                    RequestRow.idempotency_key == idempotency_key,
                )
            )
            return self.get_task(row.task_id) if row is not None else None

    def save_plan(self, plan: Plan) -> Plan:
        with self.transaction() as database:
            database.add(
                PlanRow(id=plan.id, task_id=plan.task_id, plan_json=plan.model_dump_json())
            )
            task = self._required_task_row(database, plan.task_id)
            self._append_event(
                database, task.session_id, "plan.created", plan.model_dump(mode="json")
            )
        return plan

    def get_plan_for_task(self, task_id: str) -> Plan:
        with DbSession(self.engine) as database:
            row = database.scalar(select(PlanRow).where(PlanRow.task_id == task_id))
            if row is None:
                raise KeyError(task_id)
            return Plan.model_validate_json(row.plan_json)

    def create_approval(self, approval: Approval) -> Approval:
        with self.transaction() as database:
            database.add(
                ApprovalRow(
                    id=approval.id,
                    task_id=approval.task_id,
                    proposal_id=approval.proposal_id,
                    status=approval.status.value,
                    decision_reason=None,
                    decision_key=None,
                    created_at=approval.created_at,
                    decided_at=None,
                )
            )
            task = self._required_task_row(database, approval.task_id)
            self._append_event(
                database, task.session_id, "approval.requested", approval.model_dump(mode="json")
            )
        return approval

    def get_approval(self, approval_id: str) -> Approval:
        with DbSession(self.engine) as database:
            row = database.get(ApprovalRow, approval_id)
            if row is None:
                raise KeyError(approval_id)
            return self._approval(row)

    def list_approvals(self, task_id: str) -> list[Approval]:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(ApprovalRow)
                .where(ApprovalRow.task_id == task_id)
                .order_by(ApprovalRow.created_at)
            )
            return [self._approval(row) for row in rows]

    def decide_approval(
        self, approval_id: str, status: ApprovalStatus, decision_key: str
    ) -> tuple[Approval, bool]:
        if status is ApprovalStatus.PENDING:
            raise ValueError("A decision must approve or reject")
        with self.transaction() as database:
            row = database.get(ApprovalRow, approval_id)
            if row is None:
                raise KeyError(approval_id)
            if row.decision_key is not None:
                if row.decision_key != decision_key or row.status != status.value:
                    raise ValueError("Approval already has a different decision")
                return self._approval(row), False
            row.status = status.value
            row.decision_key = decision_key
            row.decision_reason = (
                "user_approved" if status is ApprovalStatus.APPROVED else "user_rejected"
            )
            row.decided_at = utc_now()
            approval = self._approval(row)
            task = self._required_task_row(database, row.task_id)
            self._append_event(
                database, task.session_id, "approval.decided", approval.model_dump(mode="json")
            )
            return approval, True

    def save_execution(self, execution: ToolExecution) -> ToolExecution:
        with self.transaction() as database:
            database.add(
                ExecutionRow(
                    id=execution.id,
                    task_id=execution.task_id,
                    proposal_id=execution.proposal_id,
                    tool_name=execution.tool_name,
                    succeeded=execution.succeeded,
                    output_json=json.dumps(execution.output),
                    error=execution.error,
                    created_at=execution.created_at,
                )
            )
            task = self._required_task_row(database, execution.task_id)
            self._append_event(
                database, task.session_id, "tool.executed", execution.model_dump(mode="json")
            )
        return execution

    def list_executions(self, task_id: str) -> list[ToolExecution]:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(ExecutionRow)
                .where(ExecutionRow.task_id == task_id)
                .order_by(ExecutionRow.created_at)
            )
            return [self._execution(row) for row in rows]

    def save_verification(self, verification: VerificationResult) -> VerificationResult:
        with self.transaction() as database:
            database.add(VerificationRow(**verification.model_dump(exclude={"schema_version"})))
            task = self._required_task_row(database, verification.task_id)
            self._append_event(
                database, task.session_id, "tool.verified", verification.model_dump(mode="json")
            )
        return verification

    def list_verifications(self, task_id: str) -> list[VerificationResult]:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(VerificationRow)
                .where(VerificationRow.task_id == task_id)
                .order_by(VerificationRow.created_at)
            )
            return [self._verification(row) for row in rows]

    def save_provider_metadata(
        self, metadata: ProviderResponseMetadata
    ) -> ProviderResponseMetadata:
        with self.transaction() as database:
            database.add(
                ProviderResponseRow(
                    id=metadata.id,
                    task_id=metadata.task_id,
                    metadata_json=metadata.model_dump_json(),
                )
            )
            task = self._required_task_row(database, metadata.task_id)
            self._append_event(
                database,
                task.session_id,
                "provider.metadata",
                metadata.model_dump(mode="json"),
            )
        return metadata

    def get_provider_metadata(self, task_id: str) -> ProviderResponseMetadata:
        with DbSession(self.engine) as database:
            row = database.scalar(
                select(ProviderResponseRow).where(ProviderResponseRow.task_id == task_id)
            )
            if row is None:
                raise KeyError(task_id)
            return ProviderResponseMetadata.model_validate_json(row.metadata_json)

    @staticmethod
    def _required_task_row(database: DbSession, task_id: str) -> TaskRow:
        task = database.get(TaskRow, task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    @staticmethod
    def _approval(row: ApprovalRow) -> Approval:
        return Approval(
            id=row.id,
            task_id=row.task_id,
            proposal_id=row.proposal_id,
            status=ApprovalStatus(row.status),
            decision_reason=row.decision_reason,
            created_at=row.created_at,
            decided_at=row.decided_at,
        )

    @staticmethod
    def _execution(row: ExecutionRow) -> ToolExecution:
        return ToolExecution(
            id=row.id,
            task_id=row.task_id,
            proposal_id=row.proposal_id,
            tool_name=row.tool_name,
            succeeded=row.succeeded,
            output=json.loads(row.output_json),
            error=row.error,
            created_at=row.created_at,
        )

    @staticmethod
    def _verification(row: VerificationRow) -> VerificationResult:
        return VerificationResult(
            id=row.id,
            task_id=row.task_id,
            execution_id=row.execution_id,
            succeeded=row.succeeded,
            detail=row.detail,
            created_at=row.created_at,
        )
