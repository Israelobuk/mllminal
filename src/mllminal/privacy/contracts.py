"""Versioned contracts for the privacy and consent boundary."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mllminal.contracts import Contract, new_id, utc_now


class CaptureCategory(StrEnum):
    DEVICE_METADATA = "DEVICE_METADATA"
    SEMANTIC_POINTER = "SEMANTIC_POINTER"
    KEYBOARD_SHORTCUTS = "KEYBOARD_SHORTCUTS"
    TEXT_ENTRY_METADATA = "TEXT_ENTRY_METADATA"
    TEMPORARY_VISION = "TEMPORARY_VISION"
    RAW_COORDINATES = "RAW_COORDINATES"
    RAW_TEXT = "RAW_TEXT"


class CaptureMode(StrEnum):
    DISABLED = "disabled"
    METADATA = "metadata"
    MINIMIZED = "minimized"


class PrivacyRuleType(StrEnum):
    APPLICATION = "application"
    EXECUTABLE_PATH = "executable_path"
    APPLICATION_CATEGORY = "application_category"
    FOLDER = "folder"
    FILE_EXTENSION = "file_extension"
    WINDOW_TITLE = "window_title"
    BROWSER_DOMAIN = "browser_domain"


class PrivacyDecisionType(StrEnum):
    ALLOWED = "allowed"
    REJECTED = "rejected"


class SensitiveControlClassification(StrEnum):
    NONE = "none"
    SECURE = "secure"
    PASSWORD = "password"
    PIN = "pin"
    RECOVERY_CODE = "recovery_code"
    AUTHENTICATION_TOKEN = "authentication_token"
    PAYMENT_CARD = "payment_card"
    CREDENTIAL_PROMPT = "credential_prompt"
    PASSWORD_MANAGER = "password_manager"


def default_capture_modes() -> dict[CaptureCategory, CaptureMode]:
    return {category: CaptureMode.DISABLED for category in CaptureCategory}


class RetentionPolicy(Contract):
    retention_days: int = Field(default=30, ge=0)


class PrivacyPolicy(Contract):
    observation_enabled: bool = False
    paused: bool = False
    capture_modes: dict[CaptureCategory, CaptureMode] = Field(default_factory=default_capture_modes)
    retention: RetentionPolicy = Field(default_factory=RetentionPolicy)


class PrivacyRule(Contract):
    rule_id: str = Field(default_factory=new_id)
    rule_type: PrivacyRuleType
    pattern: str = Field(min_length=1)
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class ConsentRecord(Contract):
    id: str = Field(default_factory=new_id)
    granted_at: datetime | None = None
    revoked_at: datetime | None = None
    adapter: str = "local-cli"


class IncognitoSession(Contract):
    id: str = Field(default_factory=new_id)
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: datetime | None = None


class EmergencyStopState(Contract):
    active: bool = False
    stopped_at: datetime | None = None
    reason: str | None = None


class PrivacyDecision(Contract):
    event_category: CaptureCategory
    decision: PrivacyDecisionType
    rule_id: str | None = None
    reason: str
    timestamp: datetime = Field(default_factory=utc_now)
    adapter: str = "local"


class PrivacyAuditEvent(Contract):
    event_category: CaptureCategory
    decision: PrivacyDecisionType
    rule_id: str | None = None
    reason: str
    timestamp: datetime = Field(default_factory=utc_now)
    adapter: str = "local"


class CaptureContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    application: str | None = None
    executable_path: str | None = None
    application_category: str | None = None
    folder_path: str | None = None
    file_extension: str | None = None
    window_title: str | None = None
    browser_domain: str | None = None
    secure_control: SensitiveControlClassification = SensitiveControlClassification.NONE
    adapter: str = "local"


class CaptureRequest(Contract):
    category: CaptureCategory
    payload: dict[str, Any] = Field(default_factory=dict)
    context: CaptureContext = Field(default_factory=CaptureContext)


class CapturedRecord(Contract):
    id: str = Field(default_factory=new_id)
    category: CaptureCategory
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now)
    adapter: str = "local"


class CaptureResult(Contract):
    accepted: bool
    decision: PrivacyDecision
    audit: PrivacyAuditEvent
    record: CapturedRecord | None = None


class PrivacyStatus(Contract):
    observation_enabled: bool
    paused: bool
    consent_granted: bool
    incognito_active: bool
    emergency_stop_active: bool
    capture_modes: dict[CaptureCategory, CaptureMode]
    retention: RetentionPolicy
    exclusion_count: int


class DeletionRequest(Contract):
    before: datetime | None = None


class HistoryExportRequest(Contract):
    before: datetime | None = None


class PrivacyStreamEvent(Contract):
    sequence: int = Field(ge=1)
    event_type: str
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
