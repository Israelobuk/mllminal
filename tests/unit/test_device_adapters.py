from datetime import UTC, datetime

from mllminal.device.contracts import RawDeviceSignal, normalize_signal


def test_window_titles_are_redacted_before_normalization() -> None:
    event = normalize_signal(
        RawDeviceSignal(
            event_type="window.title_changed",
            source="windows.window",
            timestamp=datetime.now(UTC),
            payload={"process_name": "OUTLOOK.EXE", "title": "Payroll - secret.xlsx"},
        )
    )

    assert event.window is not None
    assert event.window.title_redacted is True
    assert "Payroll" not in event.model_dump_json()
