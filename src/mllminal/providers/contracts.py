"""Stable contracts shared by capability providers and the workflow runtime."""

from enum import StrEnum
from typing import Any, Protocol

from pydantic import Field

from mllminal.contracts import Contract


class AbstractCapability(StrEnum):
    APPLICATION_LAUNCH = "application.launch"
    APPLICATION_FOCUS = "application.focus"
    APPLICATION_CLOSE = "application.close"
    APPLICATION_INSPECT_STATE = "application.inspect_state"
    WINDOW_FIND = "window.find"
    WINDOW_FOCUS = "window.focus"
    WINDOW_MOVE = "window.move"
    WINDOW_RESIZE = "window.resize"
    CONTROL_FIND = "control.find"
    CONTROL_INVOKE = "control.invoke"
    CONTROL_SELECT = "control.select"
    CONTROL_READ_STATE = "control.read_state"
    FIELD_SET = "field.set"
    FIELD_CLEAR = "field.clear"
    FIELD_SELECT = "field.select"
    FIELD_VERIFY = "field.verify"
    KEYBOARD_SHORTCUT = "keyboard.shortcut"
    KEYBOARD_TEXT_INTENT = "keyboard.text_intent"
    POINTER_CLICK = "pointer.click"
    POINTER_DOUBLE_CLICK = "pointer.double_click"
    POINTER_CONTEXT_MENU = "pointer.context_menu"
    POINTER_DRAG = "pointer.drag"
    MENU_OPEN = "menu.open"
    MENU_SELECT = "menu.select"
    DIALOG_DETECT = "dialog.detect"
    DIALOG_CONFIRM = "dialog.confirm"
    DIALOG_CANCEL = "dialog.cancel"
    BROWSER_NAVIGATE = "browser.navigate"
    BROWSER_INSPECT_DOM = "browser.inspect_dom"
    BROWSER_EXTRACT_STRUCTURED = "browser.extract_structured"
    BROWSER_DOWNLOAD = "browser.download"
    FILE_LOCATE = "file.locate"
    FILE_COPY = "file.copy"
    FILE_MOVE = "file.move"
    FILE_RENAME = "file.rename"
    FILE_TRANSFORM = "file.transform"
    FILE_VERIFY = "file.verify"
    DOCUMENT_OPEN = "document.open"
    DOCUMENT_EDIT = "document.edit"
    DOCUMENT_SAVE = "document.save"
    DOCUMENT_EXPORT = "document.export"
    TABLE_READ = "table.read"
    TABLE_WRITE = "table.write"
    TABLE_APPEND = "table.append"
    TABLE_VERIFY = "table.verify"
    DRAFT_CREATE = "draft.create"
    DRAFT_ATTACH = "draft.attach"
    DRAFT_VERIFY_UNSENT = "draft.verify_unsent"
    STATE_WAIT = "state.wait"
    STATE_VERIFY = "state.verify"
    RESULT_CAPTURE = "result.capture"
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
