"""Background lifecycle for the consent-controlled native Windows observer."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from mllminal.device.observer import DeviceObserver


class WindowsObservationRuntime:
    def __init__(
        self,
        observer: DeviceObserver,
        interval_seconds: float = 0.25,
        emergency_stop_active: Callable[[], bool] | None = None,
    ) -> None:
        self.observer = observer
        self.interval_seconds = interval_seconds
        self.emergency_stop_active = emergency_stop_active
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.RLock()
        self._started_adapters: list[Any] = []
        self._active = False

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            stale_thread = self._thread
            self._thread = None
        if stale_thread is not None:
            stale_thread.join()

        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if self.emergency_stop_active and self.emergency_stop_active():
                self.observer.pause()
                return
            self._stop.clear()
            self.observer.start()
            started: list[Any] = []
            try:
                for adapter in self.observer.adapters:
                    start = getattr(adapter, "start", None)
                    if callable(start):
                        start()
                        started.append(adapter)
                self._started_adapters = started
                self._thread = threading.Thread(
                    target=self._run, name="mllminal-windows-observer", daemon=False
                )
                self._active = True
                self._thread.start()
            except Exception:
                self._stop.set()
                for adapter in reversed(started):
                    stop = getattr(adapter, "stop", None)
                    if callable(stop):
                        stop()
                self._started_adapters = []
                self._active = False
                self.observer.stop()
                raise

    def stop(self) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if not self._active and not self._started_adapters:
                return
            self._active = False
            self._stop.set()
            self.observer.stop()

        self._stop_adapters(name="windows.input")
        if thread is not None and thread is not threading.current_thread():
            thread.join()
        self._stop_adapters()
        with self._lifecycle_lock:
            if self._thread is thread:
                self._thread = None

    def pause(self) -> None:
        self.observer.pause()

    def resume(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self.start()
        else:
            self.observer.resume()

    def emergency_stop(self) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if not self._active and not self._started_adapters:
                return
            self._active = False
            self._stop.set()
            self.observer.pause()

        self._stop_adapters(name="windows.input")
        if thread is not None and thread is not threading.current_thread():
            thread.join()
        self._stop_adapters()
        with self._lifecycle_lock:
            if self._thread is thread:
                self._thread = None

    def _stop_adapters(self, name: str | None = None) -> None:
        with self._lifecycle_lock:
            selected = [
                adapter
                for adapter in self._started_adapters
                if name is None or getattr(adapter, "name", None) == name
            ]
            self._started_adapters = [
                adapter for adapter in self._started_adapters if adapter not in selected
            ]
        for adapter in reversed(selected):
            stop = getattr(adapter, "stop", None)
            if callable(stop):
                stop()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if self.emergency_stop_active and self.emergency_stop_active():
                    self.observer.pause()
                    return
                self.observer.poll()
                self.observer.drain()
                self._stop.wait(self.interval_seconds)
        finally:
            self._stop.set()
            self._stop_adapters()
            with self._lifecycle_lock:
                self._active = False
