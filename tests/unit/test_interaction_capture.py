from pathlib import Path

import pytest

from mllminal.interaction.contracts import (
    InteractionEvent,
    InteractionKind,
    NavigationKey,
    PointerMetadata,
    SemanticTarget,
    TextEntryMetadata,
)
from mllminal.interaction.service import InteractionService
from mllminal.privacy.contracts import CaptureCategory, CaptureMode, PrivacyPolicy
from mllminal.privacy.service import PrivacyService


def services(tmp_path: Path) -> tuple[PrivacyService, InteractionService]:
    privacy = PrivacyService(tmp_path / "state.db")
    interaction = InteractionService(tmp_path / "state.db", privacy)
    privacy.enable(idempotency_key="enable")
    policy = privacy.policy()
    privacy.update_policy(
        PrivacyPolicy(
            observation_enabled=True,
            capture_modes={
                **policy.capture_modes,
                CaptureCategory.SEMANTIC_POINTER: CaptureMode.METADATA,
                CaptureCategory.KEYBOARD_SHORTCUTS: CaptureMode.METADATA,
                CaptureCategory.TEXT_ENTRY_METADATA: CaptureMode.METADATA,
            },
        ),
        idempotency_key="policy",
    )
    return privacy, interaction


def test_semantic_target_capture_minimizes_coordinates_by_default(tmp_path: Path) -> None:
    _privacy, interaction = services(tmp_path)
    event = InteractionEvent(
        kind=InteractionKind.CONTROL_INVOKED,
        target=SemanticTarget(
            application="Excel",
            window="Book1",
            control_role="button",
            control_name="Export",
            automation_id="export-button",
            action_type="invoke",
        ),
        pointer=PointerMetadata(x=924, y=510),
    )

    result = interaction.capture(event, idempotency_key="event-1")

    assert result.accepted is True
    assert result.event is not None
    assert result.event.target.control_name == "Export"
    assert result.event.pointer is None
    assert result.event.replayable is True


def test_coordinate_only_capture_requires_explicit_raw_coordinate_mode(tmp_path: Path) -> None:
    privacy, interaction = services(tmp_path)
    event = InteractionEvent(
        kind=InteractionKind.MOUSE_CLICK,
        pointer=PointerMetadata(x=20, y=30, button="left"),
    )

    rejected = interaction.capture(event, idempotency_key="event-2")
    assert rejected.accepted is False
    assert rejected.reason == "capture_category_disabled"

    privacy.update_policy(
        PrivacyPolicy(
            observation_enabled=True,
            capture_modes={
                **privacy.policy().capture_modes,
                CaptureCategory.RAW_COORDINATES: CaptureMode.METADATA,
            },
        ),
        idempotency_key="raw-policy",
    )
    accepted = interaction.capture(event, idempotency_key="event-3")
    assert accepted.accepted is True
    assert accepted.event is not None
    assert accepted.event.replayable is False
    assert accepted.event.pointer is not None


def test_shortcuts_navigation_and_text_entry_store_only_semantic_metadata(
    tmp_path: Path,
) -> None:
    _privacy, interaction = services(tmp_path)
    shortcut = interaction.capture(
        InteractionEvent(kind=InteractionKind.KEYBOARD_SHORTCUT, shortcut="ctrl+s"),
        idempotency_key="event-4",
    )
    navigation = interaction.capture(
        InteractionEvent(
            kind=InteractionKind.KEYBOARD_NAVIGATION,
            navigation_key=NavigationKey.TAB,
        ),
        idempotency_key="event-5",
    )
    text = interaction.capture(
        InteractionEvent(
            kind=InteractionKind.TEXT_ENTRY_COMPLETED,
            text_metadata=TextEntryMetadata(
                field_classification="search",
                length_bucket="10-24",
                correction_count=1,
                paste=False,
                completed=True,
            ),
        ),
        idempotency_key="event-6",
    )

    assert shortcut.accepted is True
    assert shortcut.event.shortcut == "CTRL+S" if shortcut.event else False
    assert navigation.accepted is True
    assert navigation.event.navigation_key is NavigationKey.TAB if navigation.event else False
    assert text.accepted is True
    assert text.event is not None
    assert "raw_text" not in text.event.model_dump()
    with pytest.raises(ValueError):
        TextEntryMetadata.model_validate(
            {"field_classification": "search", "raw_text": "secret"}
        )


def test_secure_text_is_rejected_and_replay_permission_is_separate(tmp_path: Path) -> None:
    privacy, interaction = services(tmp_path)
    secure = interaction.capture(
        InteractionEvent(
            kind=InteractionKind.TEXT_ENTRY_COMPLETED,
            text_metadata=TextEntryMetadata(
                field_classification="password",
                length_bucket="10-24",
                completed=True,
                secure_control="password",
            ),
        ),
        idempotency_key="event-secure",
    )
    assert secure.accepted is False
    assert secure.reason == "secure_control"

    event = interaction.capture(
        InteractionEvent(kind=InteractionKind.KEYBOARD_SHORTCUT, shortcut="ESC"),
        idempotency_key="event-replay",
    ).event
    assert event is not None
    with pytest.raises(PermissionError, match="replay permission"):
        interaction.prepare_replay(event.id, idempotency_key="replay-1")

    interaction.authorize_replay(idempotency_key="authorize-replay")
    plan = interaction.prepare_replay(event.id, idempotency_key="replay-2")
    assert plan.event.id == event.id
    interaction.revoke_replay(idempotency_key="revoke-replay")
    with pytest.raises(PermissionError, match="replay permission"):
        interaction.prepare_replay(event.id, idempotency_key="replay-3")
    assert privacy.status().consent_granted is True


def test_visible_capture_status_tracks_privacy_consent(tmp_path: Path) -> None:
    privacy = PrivacyService(tmp_path / "state.db")
    interaction = InteractionService(tmp_path / "state.db", privacy)

    assert interaction.status().visible_status == "OBSERVATION OFF"
    privacy.enable(idempotency_key="enable-visible")
    assert interaction.status().visible_status == "OBSERVATION ON"

