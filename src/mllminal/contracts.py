"""Versioned public contracts shared by every MLLminal interface."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from uuid6 import uuid7


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid7())


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = "v1"


class MessageRole(StrEnum):
    USER = "user"
    MIL = "mil"
    SYSTEM = "system"


class TaskState(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Session(Contract):
    id: str = Field(default_factory=new_id)
    workspace_root: str
    created_at: datetime = Field(default_factory=utc_now)


class Message(Contract):
    id: str = Field(default_factory=new_id)
    session_id: str
    role: MessageRole
    content: str
    created_at: datetime = Field(default_factory=utc_now)


class Task(Contract):
    id: str = Field(default_factory=new_id)
    session_id: str
    title: str
    goal: str
    state: TaskState = TaskState.CREATED
    origin_interface: str = "api"
    blocker: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ToolProposal(Contract):
    id: str = Field(default_factory=new_id)
    tool_name: str
    arguments: dict[str, Any]
    risk: RiskLevel
    required_permission: str
    reversible: bool
    verifier: str


class PlanStep(Contract):
    id: str = Field(default_factory=new_id)
    position: int = Field(ge=1)
    title: str
    proposal: ToolProposal


class Plan(Contract):
    id: str = Field(default_factory=new_id)
    task_id: str
    steps: list[PlanStep]
    created_at: datetime = Field(default_factory=utc_now)


class Approval(Contract):
    id: str = Field(default_factory=new_id)
    task_id: str
    proposal_id: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    decision_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    decided_at: datetime | None = None


class ToolExecution(Contract):
    id: str = Field(default_factory=new_id)
    task_id: str
    proposal_id: str
    tool_name: str
    succeeded: bool
    output: dict[str, Any]
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class VerificationResult(Contract):
    id: str = Field(default_factory=new_id)
    task_id: str
    execution_id: str
    succeeded: bool
    detail: str
    created_at: datetime = Field(default_factory=utc_now)


class PermissionGrant(Contract):
    id: str = Field(default_factory=new_id)
    permission: str
    workspace_root: str
    allowed: bool = True


class EventEnvelope(Contract):
    session_id: str
    sequence: int = Field(ge=1)
    event_type: str
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now)


class ErrorEnvelope(Contract):
    code: str
    message: str
    retryable: bool = False
    detail: dict[str, Any] = Field(default_factory=dict)
