from pathlib import Path

import pytest

from mllminal.contracts import utc_now
from mllminal.device.contracts import RawDeviceSignal, normalize_signal
from mllminal.interaction.contracts import InteractionEvent, InteractionKind, SemanticTarget
from mllminal.learning.profile_contracts import (
    BackendOutcomeRequest,
    ProfileExperienceRequest,
    ProfileExperienceType,
    ProfileOutcome,
)
from mllminal.learning.profiles import ApplicationInteractionProfileService
from mllminal.learning.replay import LearningRepository


def _service(path: Path) -> ApplicationInteractionProfileService:
    repository = LearningRepository(path)
    repository.initialize()
    return ApplicationInteractionProfileService(repository)


def _device_event(event_type: str, *, sequence: int, **payload: object):
    return normalize_signal(
        RawDeviceSignal(
            event_type=event_type,
            source="windows.uia",
            timestamp=utc_now(),
            payload={
                "process_name": "explorer.exe",
                "executable_path": r"C:\Windows\explorer.exe",
                "application_class": "File Explorer",
                "window_class": "CabinetWClass",
                "title_classification": "document",
                **payload,
            },
        )
    ).model_copy(update={"monotonic_sequence": sequence})


def test_profile_aggregates_semantic_controls_shortcuts_and_restart(tmp_path: Path) -> None:
    database = tmp_path / "learning.db"
    service = _service(database)

    first = service.observe_device_event(
        _device_event(
            "control.focused",
            sequence=1,
            control_type="button",
            name="Open",
            automation_id="open-button",
            class_name="Button",
        )
    )
    second = service.observe_device_event(
        _device_event(
            "control.focused",
            sequence=2,
            control_type="button",
            name="Open",
            automation_id="open-button",
            class_name="Button",
        )
    )
    shortcut = service.observe_device_event(
        _device_event("keyboard.shortcut", sequence=3, shortcut="ctrl+o")
    )

    assert first is not None
    assert second is not None
    assert second.profile_id == first.profile_id
    assert second.observation_count == 2
    assert shortcut.observation_count == 3
    assert second.accessibility_support_level == "ui_automation"
    assert second.stable_automation_ids == ["open-button"]
    assert shortcut.observed_keyboard_shortcuts == ["CTRL+O"]
    assert shortcut is not None

    restarted = _service(database)
    persisted = restarted.profile(first.profile_id)
    assert persisted.observation_count == 3
    assert persisted.discovered_controls[0].observation_count == 2


def test_secure_fields_and_sensitive_interaction_labels_are_not_learned(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path / "learning.db")
    secure_device = _device_event(
        "control.focused",
        sequence=1,
        control_type="edit",
        name="Password",
        automation_id="password-input",
        secure=True,
    )
    assert service.observe_device_event(secure_device) is None

    secure_interaction = InteractionEvent(
        kind=InteractionKind.CONTROL_INVOKED,
        target=SemanticTarget(
            application="Terminal",
            window="Authentication",
            control_role="edit",
            control_name="token value",
            automation_id="auth-input",
        ),
    )
    assert service.observe_interaction(secure_interaction) is None
    assert service.list_profiles() == []


def test_reliability_updates_experience_and_ranks_reliable_backend(tmp_path: Path) -> None:
    database = tmp_path / "learning.db"
    service = _service(database)
    profile = service.observe_device_event(_device_event("application.focused", sequence=1))
    assert profile is not None

    service.record_backend_outcome(
        BackendOutcomeRequest(
            profile_id=profile.profile_id,
            abstract_action="control.invoke",
            backend="windows.uia",
            target_type="button",
            verification_method="state.verify",
            outcome=ProfileOutcome.FAILED,
            succeeded=False,
            provenance={"reason": "target_not_found"},
        ),
        idempotency_key="outcome-1",
    )
    service.record_backend_outcome(
        BackendOutcomeRequest(
            profile_id=profile.profile_id,
            abstract_action="control.invoke",
            backend="local.vision",
            target_type="button",
            verification_method="visual.state",
            outcome=ProfileOutcome.VERIFIED,
            succeeded=True,
            verification_passed=True,
            provenance={"source": "verified_state"},
        ),
        idempotency_key="outcome-2",
    )

    resolution = service.rank_backends(
        profile.profile_id,
        "control.invoke",
        "button",
        ("windows.uia", "local.vision"),
    )
    assert resolution.selected_backend == "local.vision"
    assert resolution.reliability_by_backend["local.vision"] > 0.0
    assert len(service.experiences(profile.profile_id)) == 2

    accepted = service.record_experience(
        ProfileExperienceRequest(
            profile_id=profile.profile_id,
            experience_type=ProfileExperienceType.WORKFLOW_SUGGESTION,
            outcome=ProfileOutcome.ACCEPTED,
            provenance={"candidate_id": "candidate-1"},
        ),
        idempotency_key="suggestion-1",
    )
    assert accepted.reward > 0


def test_profile_contract_rejects_prohibited_profile_content() -> None:
    with pytest.raises(ValueError, match="prohibited"):
        from mllminal.learning.profile_contracts import ApplicationInteractionProfile

        ApplicationInteractionProfile(
            application_identity="browser",
            executable_name="browser.exe",
            observed_window_titles=["password reset"],
        )
