from datetime import UTC, datetime

import pytest

from mllminal.device.contracts import (
    ApplicationIdentity,
    NormalizedDeviceEvent,
    RawDeviceSignal,
    normalize_signal,
)


def test_normalizes_metadata_only_foreground_signal() -> None:
    event = normalize_signal(
        RawDeviceSignal(
            event_type="application.focused",
            source="windows.foreground",
            timestamp=datetime.now(UTC),
            payload={"process_name": "EXCEL.EXE", "publisher": "Microsoft Corporation"},
        )
    )

    assert isinstance(event, NormalizedDeviceEvent)
    assert event.event_type == "application.focused"
    assert event.application == ApplicationIdentity(
        process_name="EXCEL.EXE", publisher="Microsoft Corporation"
    )


def test_rejects_raw_text_and_credential_payloads() -> None:
    for field in ("typed_text", "password", "clipboard", "token", "screenshot"):
        with pytest.raises(ValueError, match="forbidden"):
            normalize_signal(
                RawDeviceSignal(
                    event_type="window.focused",
                    source="windows.fixture",
                    timestamp=datetime.now(UTC),
                    payload={field: "secret"},
                )
            )
