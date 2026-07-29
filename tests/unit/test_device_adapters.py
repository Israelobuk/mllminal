import threading
from datetime import UTC, datetime

from mllminal.device.contracts import RawDeviceSignal, normalize_signal
from mllminal.device.windows_adapters import (
    WindowsInputHookAdapter,
    WindowsUIAutomationAdapter,
)


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


def test_input_hook_stop_is_idempotent_and_blocks_late_callbacks() -> None:
    adapter = WindowsInputHookAdapter(
        use_native=False,
        focused_control=lambda: {"control_type": "edit", "secure": False},
    )
    adapter.enabled = True
    adapter._modifiers = lambda: set()
    exited = threading.Event()

    def fake_pump() -> None:
        adapter._ready.set()
        adapter._stop.wait()
        exited.set()

    adapter._pump = fake_pump
    adapter.start()
    adapter.start()
    adapter._keyboard_event(0x41)
    assert adapter.poll()

    adapter.stop()
    adapter.stop()
    adapter._keyboard_event(0x41)

    assert exited.is_set()
    assert adapter.poll() == []
    assert adapter._thread is None


def test_ui_automation_failure_is_safe_and_resources_are_released() -> None:
    class FailingClient:
        def Dispatch(self, _name):
            raise RuntimeError("UI Automation unavailable")

    adapter = WindowsUIAutomationAdapter(use_native=True, client_module=FailingClient())
    assert adapter.focused_metadata() is None

    released = []

    class OleObject:
        def Release(self) -> None:
            released.append(True)

    class Automation:
        _oleobj_ = OleObject()

    adapter._automation = Automation()
    adapter.stop()
    assert released == [True]
