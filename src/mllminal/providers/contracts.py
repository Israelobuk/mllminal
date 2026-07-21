"""Stable contracts shared by capability providers and the workflow runtime."""

from enum import StrEnum
from typing import Any, Protocol

from pydantic import Field

from mllminal.contracts import Contract


class AbstractCapability(StrEnum):
    SPREADSHEET_INSPECT = "spreadsheet.inspect"
    SPREADSHEET_EXPORT_PDF = "spreadsheet.export_pdf"
    SPREADSHEET_VERIFY_OUTPUT = "spreadsheet.verify_output"
    EMAIL_CREATE_DRAFT = "email.create_draft"
    EMAIL_SET_RECIPIENTS = "email.set_recipients"
    EMAIL_SET_SUBJECT = "email.set_subject"
    EMAIL_SET_BODY = "email.set_body"
    EMAIL_ATTACH_FILE = "email.attach_file"
    EMAIL_VERIFY_DRAFT = "email.verify_draft"


class ProviderKind(StrEnum):
    NATIVE = "native"
    BROWSER = "browser"
    BUNDLED = "bundled"
    PORTABLE = "portable"
    MANUAL = "manual"
    UNSUPPORTED = "unsupported"


class ProviderStatus(StrEnum):
    AVAILABLE = "available"
    DETECTED = "detected"
    MANUAL_REQUIRED = "manual_required"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


class ProviderAvailability(Contract):
    provider: str
    display_name: str
    kind: ProviderKind
    status: ProviderStatus
    detected: bool = False
    capabilities: list[AbstractCapability] = Field(default_factory=list)
    permission_scopes: list[str] = Field(default_factory=list)
    verification_strength: str = "none"
    version: str | None = None
    install_state: str = "not_installed"
    explanation: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityResolution(Contract):
    capability: AbstractCapability
    status: ProviderStatus
    provider: str | None = None
    provider_kind: ProviderKind = ProviderKind.UNSUPPORTED
    available_providers: list[str] = Field(default_factory=list)
    explanation: str
    manual_steps: list[str] = Field(default_factory=list)


class ProviderRequest(Contract):
    capability: AbstractCapability
    arguments: dict[str, Any] = Field(default_factory=dict)
    preview: bool = True
    workflow_authorized: bool = False
    action_approved: bool = False


class ProviderResult(Contract):
    capability: AbstractCapability
    provider: str
    succeeded: bool
    preview: bool
    draft_only: bool = False
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class CapabilityProvider(Protocol):
    name: str
    display_name: str
    kind: ProviderKind
    priority: int

    async def discover(self) -> ProviderAvailability:
        """Return availability without reading credentials or making changes."""

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        """Execute a bounded capability under the provider's safety policy."""
