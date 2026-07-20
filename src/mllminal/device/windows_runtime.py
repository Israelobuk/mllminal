"""Background lifecycle for the consent-controlled native Windows observer."""

from __future__ import annotations

import threading


from mllminal.device.observer import DeviceObserver


class WindowsObservationRuntime:
    def __init__(self, observer: DeviceObserver, interval_seconds: float = 0.25) -> None:
        self.observer = observer
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self.observer.start()
        for adapter in self.observer.adapters:
            start = getattr(adapter, "start", None)
            if callable(start):
                start()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mllminal-windows-observer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        for adapter in self.observer.adapters:
            stop = getattr(adapter, "stop", None)
            if callable(stop):
                stop()
        self.observer.stop()

    def pause(self) -> None:
        self.observer.pause()

    def resume(self) -> None:
        if self._thread is None:
            self.start()
        else:
            self.observer.resume()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.observer.poll()
            self.observer.drain()
            self._stop.wait(self.interval_seconds)




