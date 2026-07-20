"""Contracts for the Windows product acceptance scenario."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from mllminal.contracts import Contract, new_id, utc_now


class AcceptanceStage(StrEnum):
    OBSERVATION_ENABLED = "observation_enabled"
    DEMONSTRATED = "demonstrated"
    DRAFT_COMPILED = "draft_compiled"
    VARIABLES_LABELED = "variables_labeled"
    PREVIEWED = "previewed"
    APPROVED = "approved"
    FILESYSTEM_VERIFIED = "filesystem_verified"
    EXCEL_VERIFIED = "excel_verified"
    EMAIL_DRAFT_VERIFIED = "email_draft_verified"
    DESKTOP_CLI_MATCHED = "desktop_cli_matched"
    USER_REVIEWED = "user_reviewed"


class AcceptanceState(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    MANUAL_REQUIRED = "manual_required"
    PASSED = "passed"


class AcceptanceRecordRequest(Contract):
    stage: AcceptanceStage
    evidence: list[str] = Field(default_factory=list, max_length=32)
    verified: bool = False
    note: str | None = None


class AcceptanceCheck(Contract):
    name: str
    category: Literal["scenario", "security", "performance"]
    status: str
    evidence: list[str] = Field(default_factory=list)
    note: str | None = None


class AcceptanceRun(Contract):
    id: str = Field(default_factory=new_id)
    state: AcceptanceState = AcceptanceState.NOT_STARTED
    current_stage: AcceptanceStage | None = None
    checks: list[AcceptanceCheck] = Field(default_factory=list)
    no_automatic_send: Literal[True] = True
    started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
