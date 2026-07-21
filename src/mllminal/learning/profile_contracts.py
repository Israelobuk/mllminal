"""Privacy-safe application interaction profiles and backend evidence."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator

from mllminal.contracts import Contract, new_id, utc_now


class ProfileExperienceType(StrEnum):
    BACKEND_SELECTION = "backend_selection"
    TARGET_RESOLUTION = "target_resolution"
    VERIFICATION_SELECTION = "verification_selection"
    WORKFLOW_SUGGESTION = "workflow_suggestion"
    WORKFLOW_EXECUTION = "workflow_execution"
    USER_CORRECTION = "user_correction"
    ROLLBACK = "rollback"
    EMERGENCY_STOP = "emergency_stop"


class ProfileOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    VERIFIED = "verified"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CORRECTED = "corrected"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"
    EMERGENCY_STOPPED = "emergency_stopped"


class ProfileControl(Contract):
    control_role: str
    control_name: str | None = None
    automation_id: str | None = None
    class_name: str = "unknown"
    observation_count: int = Field(default=1, ge=1)
    last_seen_at: datetime = Field(default_factory=utc_now)


class ProfileBackendChoice(Contract):
    backend: str
    abstract_action: str
    target_type: str
    verification_method: str | None = None
    observation_count: int = Field(default=1, ge=1)
    last_seen_at: datetime = Field(default_factory=utc_now)


class ProfileReliabilityScore(Contract):
    backend: str
    abstract_action: str
    target_type: str
    attempts: int = Field(default=0, ge=0)
    successes: int = Field(default=0, ge=0)
    failures: int = Field(default=0, ge=0)
    verification_passes: int = Field(default=0, ge=0)
    verification_failures: int = Field(default=0, ge=0)
    reliability: float = Field(default=0.0, ge=0.0, le=1.0)
    fragility: float = Field(default=0.0, ge=0.0, le=1.0)
    last_outcome: ProfileOutcome | None = None
    last_seen_at: datetime = Field(default_factory=utc_now)


class BackendReliabilityRecord(ProfileReliabilityScore):
    record_id: str = Field(default_factory=new_id)
    profile_id: str
    verification_method: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class BackendOutcomeRequest(Contract):
    profile_id: str
    abstract_action: str
    backend: str
    target_type: str = "unknown"
    verification_method: str | None = None
    outcome: ProfileOutcome
    succeeded: bool = False
    verification_passed: bool = False
    fragility: float = Field(default=0.0, ge=0.0, le=1.0)
    provenance: dict[str, Any] = Field(default_factory=dict)


class ProfileLearningExperience(Contract):
    experience_id: str = Field(default_factory=new_id)
    profile_id: str
    experience_type: ProfileExperienceType
    abstract_action: str | None = None
    backend: str | None = None
    target_type: str | None = None
    verification_method: str | None = None
    outcome: ProfileOutcome
    reward: float
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ProfileExperienceRequest(Contract):
    profile_id: str
    experience_type: ProfileExperienceType
    abstract_action: str | None = None
    backend: str | None = None
    target_type: str | None = None
    verification_method: str | None = None
    outcome: ProfileOutcome
    provenance: dict[str, Any] = Field(default_factory=dict)


class BackendResolution(Contract):
    profile_id: str
    abstract_action: str
    target_type: str
    selected_backend: str | None = None
    ordered_backends: list[str] = Field(default_factory=list)
    reliability_by_backend: dict[str, float] = Field(default_factory=dict)
    explanation: str


class ApplicationInteractionProfile(Contract):
    profile_id: str = Field(default_factory=new_id)
    application_identity: str
    executable_path_hash: str | None = None
    executable_name: str
    application_version: str | None = None
    window_class_patterns: list[str] = Field(default_factory=list)
    observed_window_titles: list[str] = Field(default_factory=list)
    accessibility_support_level: str = "metadata_only"
    discovered_controls: list[ProfileControl] = Field(default_factory=list)
    stable_automation_ids: list[str] = Field(default_factory=list)
    stable_control_names_roles: list[str] = Field(default_factory=list)
    observed_keyboard_shortcuts: list[str] = Field(default_factory=list)
    observed_menus_dialogs: list[str] = Field(default_factory=list)
    visual_anchors: list[str] = Field(default_factory=list)
    observed_state_transitions: list[str] = Field(default_factory=list)
    successful_backend_choices: list[ProfileBackendChoice] = Field(default_factory=list)
    failed_backend_choices: list[ProfileBackendChoice] = Field(default_factory=list)
    verification_methods: list[str] = Field(default_factory=list)
    reliability_scores: list[ProfileReliabilityScore] = Field(default_factory=list)
    fragility_scores: list[ProfileReliabilityScore] = Field(default_factory=list)
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)
    observation_count: int = Field(default=0, ge=0)
    successful_execution_count: int = Field(default=0, ge=0)
    failed_execution_count: int = Field(default=0, ge=0)
    last_observed_event_type: str | None = None
    profile_version: int = Field(default=1, ge=1)

    @field_validator(
        "application_identity",
        "executable_name",
        "window_class_patterns",
        "observed_window_titles",
        "stable_automation_ids",
        "stable_control_names_roles",
        "observed_keyboard_shortcuts",
        "observed_menus_dialogs",
        "visual_anchors",
        "observed_state_transitions",
        "verification_methods",
        mode="before",
    )
    @classmethod
    def reject_raw_profile_text(cls, value: Any) -> Any:
        """Keep profile fields bounded and reject obvious credential material."""

        forbidden = ("password", "cookie", "token", "secret", "recovery", "private key")

        def check(item: Any) -> Any:
            if isinstance(item, str):
                lowered = item.casefold()
                if any(marker in lowered for marker in forbidden):
                    raise ValueError("profile field contains prohibited credential material")
                if len(item) > 256:
                    raise ValueError("profile field is too long")
            return item

        if isinstance(value, list):
            return [check(item) for item in value]
        return check(value)
