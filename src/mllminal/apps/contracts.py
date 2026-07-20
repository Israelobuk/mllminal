"""Versioned contracts for the on-device application bridge."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import Field

from mllminal.contracts import Contract, new_id, utc_now


class ApplicationState(StrEnum):
    DETECTED = "detected"
    AVAILABLE = "available"
    CONNECTED = "connected"
    CAPABILITIES_GRANTED = "capabilities_granted"
    WORKFLOW_AUTHORIZED = "workflow_authorized"
    ACTION_APPROVED = "action_approved"


class CapabilityMode(StrEnum):
    READ_ONLY = "read_only"
    PREVIEW = "preview"
    DRAFT_ONLY = "draft_only"


class ApplicationAvailability(Contract):
    application: str
    display_name: str
    detected: bool
    available: bool
    state: ApplicationState
    local_session: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityDefinition(Contract):
    name: str
    display_name: str
    mode: CapabilityMode
    permission_scope: str
    consequential: bool = False


class CapabilityRequest(Contract):
    capability: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    preview: bool = True
    workflow_authorized: bool = False
    action_approved: bool = False


class CapabilityResult(Contract):
    execution_id: str = Field(default_factory=new_id)
    capability: str
    succeeded: bool
    preview: bool
    draft_only: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class VerificationResult(Contract):
    succeeded: bool
    reason: str
    observed: dict[str, Any] = Field(default_factory=dict)


class ApplicationGrant(Contract):
    id: str = Field(default_factory=new_id)
    application: str
    scope: str
    granted: bool = True
    updated_at: datetime = Field(default_factory=utc_now)


class ApplicationAdapter(Protocol):
    name: str
    display_name: str

    async def detect(self) -> ApplicationAvailability:
        """Detect a locally available signed-in surface without reading secrets."""

    async def capabilities(self) -> list[CapabilityDefinition]:
        """Return bounded capabilities exposed by this adapter."""

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        """Execute only a bounded, granted capability."""

    async def verify(self, result: CapabilityResult) -> VerificationResult:
        """Verify the adapter result independently of model reasoning."""
