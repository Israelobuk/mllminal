import threading

from mllminal.device.windows_runtime import WindowsObservationRuntime


class FakeObserver:
    def __init__(self, adapters) -> None:
        self.adapters = adapters
        self.started = 0
        self.stopped = 0
        self.tick = threading.Event()

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def pause(self) -> None:
        pass

    def poll(self) -> None:
        self.tick.set()

    def drain(self) -> None:
        pass


class FakeAdapter:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    def start(self) -> None:
        self.calls.append(f"start:{self.name}")

    def stop(self) -> None:
        self.calls.append(f"stop:{self.name}")


def test_runtime_start_stop_is_idempotent_and_joins_in_reverse_adapter_order() -> None:
    calls: list[str] = []
    observer = FakeObserver([FakeAdapter("first", calls), FakeAdapter("second", calls)])
    runtime = WindowsObservationRuntime(observer, interval_seconds=0.001)

    runtime.start()
    assert observer.tick.wait(timeout=1)
    runtime.start()
    runtime.stop()
    runtime.stop()
    runtime.start()
    assert observer.tick.wait(timeout=1)
    runtime.stop()

    assert observer.started == 2
    assert observer.stopped == 2
    assert calls == [
        "start:first",
        "start:second",
        "stop:second",
        "stop:first",
        "start:first",
        "start:second",
        "stop:second",
        "stop:first",
    ]
    assert runtime._thread is None
