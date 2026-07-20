from datetime import timedelta
from pathlib import Path

import pytest

from mllminal.privacy.contracts import (
    CaptureCategory,
    CaptureContext,
    CaptureRequest,
    PrivacyRule,
    PrivacyRuleType,
)
from mllminal.privacy.service import PrivacyService


def service(tmp_path: Path) -> PrivacyService:
    return PrivacyService(tmp_path / "privacy.db")


def request(
    category: CaptureCategory,
    payload: dict[str, object],
    **context: str,
) -> CaptureRequest:
    return CaptureRequest(
        category=category,
        payload=payload,
        context=CaptureContext(**context),
    )


def test_observation_is_disabled_until_explicit_consent(tmp_path: Path) -> None:
    privacy = service(tmp_path)

    result = privacy.capture(
        request(CaptureCategory.DEVICE_METADATA, {"application": "Excel"}),
        idempotency_key="capture-1",
    )

    assert result.accepted is False
    assert result.decision.reason == "observation_disabled"
    assert privacy.status().consent_granted is False
    assert privacy.history() == []


def test_enable_allows_default_device_metadata_but_not_other_categories(tmp_path: Path) -> None:
    privacy = service(tmp_path)
    privacy.enable(idempotency_key="enable-1")

    metadata = privacy.capture(
        request(CaptureCategory.DEVICE_METADATA, {"application": "Excel"}),
        idempotency_key="capture-2",
    )
    pointer = privacy.capture(
        request(CaptureCategory.SEMANTIC_POINTER, {"name": "Export"}),
        idempotency_key="capture-3",
    )

    assert metadata.accepted is True
    assert pointer.accepted is False
    assert pointer.decision.reason == "capture_category_disabled"


def test_pause_and_incognito_block_persistence(tmp_path: Path) -> None:
    privacy = service(tmp_path)
    privacy.enable(idempotency_key="enable-2")
    privacy.pause(idempotency_key="pause-1")

    paused = privacy.capture(
        request(CaptureCategory.DEVICE_METADATA, {"application": "Excel"}),
        idempotency_key="capture-4",
    )
    privacy.resume(idempotency_key="resume-1")
    privacy.start_incognito(idempotency_key="incognito-1")
    incognito = privacy.capture(
        request(CaptureCategory.DEVICE_METADATA, {"application": "Excel"}),
        idempotency_key="capture-5",
    )

    assert paused.decision.reason == "observation_paused"
    assert incognito.decision.reason == "incognito_active"
    assert privacy.history() == []


def test_emergency_stop_is_durable_across_service_restart(tmp_path: Path) -> None:
    database = tmp_path / "privacy.db"
    first = PrivacyService(database)
    first.enable(idempotency_key="enable-3")
    first.emergency_stop(idempotency_key="stop-1")

    restarted = PrivacyService(database)

    assert restarted.status().emergency_stop_active is True
    assert (
        restarted.capture(
            request(CaptureCategory.DEVICE_METADATA, {"application": "Excel"}),
            idempotency_key="capture-6",
        ).decision.reason
        == "emergency_stop_active"
    )


@pytest.mark.parametrize(
    ("context", "reason"),
    [
        ({"application": "Password Manager"}, "excluded_application"),
        ({"folder_path": "C:/Users/test/Documents/Private"}, "excluded_folder"),
        ({"window_title": "Login - Bank"}, "excluded_window_title"),
    ],
)
def test_exclusions_reject_capture_without_storing_payload(
    tmp_path: Path, context: dict[str, str], reason: str
) -> None:
    privacy = service(tmp_path)
    privacy.enable(idempotency_key="enable-4")
    privacy.add_exclusion(
        PrivacyRule(
            rule_type={
                "excluded_application": PrivacyRuleType.APPLICATION,
                "excluded_folder": PrivacyRuleType.FOLDER,
                "excluded_window_title": PrivacyRuleType.WINDOW_TITLE,
            }[reason],
            pattern=next(iter(context.values())),
        ),
        idempotency_key=f"rule-{reason}",
    )

    result = privacy.capture(
        request(CaptureCategory.DEVICE_METADATA, {"secret": "do-not-store"}, **context),
        idempotency_key=f"capture-{reason}",
    )

    assert result.accepted is False
    assert result.decision.reason == reason
    assert "do-not-store" not in privacy.export_history()


def test_secure_control_and_raw_text_are_always_rejected(tmp_path: Path) -> None:
    privacy = service(tmp_path)
    privacy.enable(idempotency_key="enable-5")

    secure = privacy.capture(
        request(
            CaptureCategory.TEXT_ENTRY_METADATA,
            {"text": "password123"},
            secure_control="password",
        ),
        idempotency_key="capture-secure",
    )
    raw = privacy.capture(
        request(CaptureCategory.RAW_TEXT, {"text": "secret"}),
        idempotency_key="capture-raw",
    )

    assert secure.decision.reason == "secure_control"
    assert raw.decision.reason == "raw_text_prohibited"
    assert "password123" not in privacy.export_history()
    assert "secret" not in privacy.export_history()


def test_text_entry_is_minimized_and_audit_is_minimal(tmp_path: Path) -> None:
    privacy = service(tmp_path)
    privacy.enable(idempotency_key="enable-6")
    policy = privacy.policy().model_copy(
        update={"capture_modes": {CaptureCategory.TEXT_ENTRY_METADATA: "metadata"}}
    )
    privacy.update_policy(policy, idempotency_key="policy-1")

    result = privacy.capture(
        request(
            CaptureCategory.TEXT_ENTRY_METADATA,
            {
                "text": "secret text",
                "field_classification": "search",
                "length": 11,
                "correction_count": 2,
                "paste": False,
                "completed": True,
            },
        ),
        idempotency_key="capture-text",
    )

    assert result.accepted is True
    assert result.record is not None
    assert "secret text" not in result.record.payload
    assert result.record.payload["field_classification"] == "search"
    assert result.record.payload["length_bucket"] == "10-24"
    assert set(result.audit.model_dump()) <= {
        "schema_version",
        "event_category",
        "decision",
        "rule_id",
        "reason",
        "timestamp",
        "adapter",
    }


def test_raw_text_cannot_be_enabled_and_vision_is_disabled_by_default(tmp_path: Path) -> None:
    privacy = service(tmp_path)
    privacy.enable(idempotency_key="enable-7")
    with pytest.raises(ValueError, match="RAW_TEXT"):
        privacy.update_policy(
            privacy.policy().model_copy(
                update={"capture_modes": {CaptureCategory.RAW_TEXT: "metadata"}}
            ),
            idempotency_key="policy-raw",
        )

    vision = privacy.capture(
        request(CaptureCategory.TEMPORARY_VISION, {"raw_frame": "image-bytes"}),
        idempotency_key="capture-vision",
    )
    assert vision.decision.reason == "capture_category_disabled"


def test_retention_and_history_deletion_remove_old_records(tmp_path: Path) -> None:
    privacy = service(tmp_path)
    privacy.enable(idempotency_key="enable-8")
    privacy.capture(
        request(CaptureCategory.DEVICE_METADATA, {"application": "Excel"}),
        idempotency_key="capture-retention",
    )
    privacy.update_policy(
        privacy.policy().model_copy(update={"retention": {"retention_days": 0}}),
        idempotency_key="policy-retention",
    )

    assert privacy.history() == []
    assert (
        privacy.delete_history(
            idempotency_key="delete-history", before=privacy.now() + timedelta(days=1)
        )
        >= 0
    )
    assert privacy.history() == []
