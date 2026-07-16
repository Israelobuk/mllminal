from datetime import UTC, datetime
from pathlib import Path

from mllminal.device.contracts import RawDeviceSignal
from mllminal.device.observer import DeviceObserver, FakeDeviceAdapter


def _signal(name: str = "application.focused") -> RawDeviceSignal:
    return RawDeviceSignal(
        event_type=name,
        source="windows.fixture",
        timestamp=datetime.now(UTC),
        payload={"process_name": "EXCEL.EXE"},
    )


def test_lifecycle_pause_resume_and_capabilities(tmp_path: Path) -> None:
    observer = DeviceObserver(tmp_path, [FakeDeviceAdapter("fixture")])
    assert observer.status.state == "STOPPED"
    observer.start()
    observer.pause()
    observer.resume()
    observer.stop()
    assert observer.status.state == "STOPPED"
    assert observer.capabilities()[0].available is True


def test_backpressure_duplicates_ordering_and_persist_before_publish(tmp_path: Path) -> None:
    adapter = FakeDeviceAdapter("fixture")
    observer = DeviceObserver(tmp_path, [adapter], queue_capacity=1)
    observer.start()
    published = []
    observer.subscribe(published.append)
    assert observer.ingest(_signal()) is True
    assert observer.ingest(_signal()) is False
    assert observer.ingest(_signal("window.focused")) is False
    observer.drain()
    events = observer.events()
    assert [event.monotonic_sequence for event in events] == [1]
    assert published[0] == events[0]
    assert observer.status.dropped_events == 1
    assert observer.status.duplicate_events == 1


def test_adapter_failure_isolated_and_restart_is_durable(tmp_path: Path) -> None:
    failing = FakeDeviceAdapter("bad", failure=RuntimeError("adapter failed"))
    good = FakeDeviceAdapter("good", signals=[_signal()])
    observer = DeviceObserver(tmp_path, [failing, good])
    observer.start()
    observer.poll()
    observer.drain()
    restarted = DeviceObserver(tmp_path, [])
    assert len(restarted.events()) == 1
    assert restarted.health()["bad"].healthy is False
    assert restarted.events()[0].monotonic_sequence == 1
