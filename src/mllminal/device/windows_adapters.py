"""Native Windows metadata adapters with deterministic fixture fallbacks.

These adapters intentionally discard content at the collection boundary. They expose process,
foreground-window, UI Automation control, and safe semantic input metadata only.
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
import threading
from collections import deque
from collections.abc import Callable
from ctypes import wintypes
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any, ClassVar

from mllminal.device.contracts import RawDeviceSignal
from mllminal.device.observer import ObserverCapability


def _signal(event_type: str, source: str, payload: dict[str, Any]) -> RawDeviceSignal:
    return RawDeviceSignal(
        event_type=event_type, source=source, timestamp=datetime.now(UTC), payload=payload
    )


def _module(name: str) -> Any | None:
    try:
        return import_module(name)
    except ImportError:
        return None


def _process_path(win32api: Any, win32process: Any, win32con: Any, pid: int) -> str | None:
    handle = None
    try:
        access = int(win32con.PROCESS_QUERY_INFORMATION) | int(win32con.PROCESS_VM_READ)
        handle = win32api.OpenProcess(access, False, pid)
        return str(win32process.GetModuleFileNameEx(handle, 0)) or None
    except Exception:
        return None
    finally:
        if handle is not None:
            with contextlib.suppress(Exception):
                win32api.CloseHandle(handle)


def _process_name(path: str | None, pid: int) -> str:
    return Path(path).name if path else f"pid-{pid}"


class WindowsProcessAdapter:
    name = "windows.process"

    def __init__(
        self,
        psutil_module: Any | None = None,
        *,
        use_native: bool = False,
        win32api_module: Any | None = None,
        win32process_module: Any | None = None,
        win32con_module: Any | None = None,
    ) -> None:
        if psutil_module is None:
            psutil_module = _module("psutil")
        self.psutil = psutil_module
        self.win32api = win32api_module if use_native else None
        self.win32process = win32process_module if use_native else None
        self.win32con = win32con_module if use_native else None
        if use_native:
            self.win32api = self.win32api or _module("win32api")
            self.win32process = self.win32process or _module("win32process")
            self.win32con = self.win32con or _module("win32con")
        self._known: dict[int, tuple[str, str | None]] = {}

    def capability(self) -> ObserverCapability:
        available = self.psutil is not None or all(
            module is not None for module in (self.win32api, self.win32process, self.win32con)
        )
        return ObserverCapability(self.name, available)

    def poll(self) -> list[RawDeviceSignal]:
        if self.psutil is not None:
            current = self._psutil_snapshot()
        elif self.capability().available:
            current = self._native_snapshot()
        else:
            return []
        events = [
            _signal(
                "application.started",
                self.name,
                {
                    "process_name": identity[0],
                    "executable_path": identity[1],
                },
            )
            for pid, identity in current.items()
            if pid not in self._known
        ]
        events.extend(
            _signal(
                "application.exited",
                self.name,
                {
                    "process_name": identity[0],
                    "executable_path": identity[1],
                },
            )
            for pid, identity in self._known.items()
            if pid not in current
        )
        self._known = current
        return events

    def _psutil_snapshot(self) -> dict[int, tuple[str, str | None]]:
        assert self.psutil is not None
        current: dict[int, tuple[str, str | None]] = {}
        for process in self.psutil.process_iter(["pid", "name", "exe"]):
            try:
                info = process.info
                current[int(info["pid"])] = (
                    str(info.get("name") or "unknown"),
                    str(info["exe"]) if info.get("exe") else None,
                )
            except Exception:
                continue
        return current

    def _native_snapshot(self) -> dict[int, tuple[str, str | None]]:
        assert self.win32process is not None
        assert self.win32api is not None
        assert self.win32con is not None
        current: dict[int, tuple[str, str | None]] = {}
        for raw_pid in self.win32process.EnumProcesses():
            pid = int(raw_pid)
            path = _process_path(self.win32api, self.win32process, self.win32con, pid)
            current[pid] = (_process_name(path, pid), path)
        return current


class WindowsForegroundAdapter:
    name = "windows.foreground"

    def __init__(
        self,
        *,
        use_native: bool = False,
        win32gui_module: Any | None = None,
        win32process_module: Any | None = None,
        win32api_module: Any | None = None,
        win32con_module: Any | None = None,
    ) -> None:
        self.win32gui = win32gui_module if use_native else None
        self.win32process = win32process_module if use_native else None
        self.win32api = win32api_module if use_native else None
        self.win32con = win32con_module if use_native else None
        if use_native:
            self.win32gui = self.win32gui or _module("win32gui")
            self.win32process = self.win32process or _module("win32process")
            self.win32api = self.win32api or _module("win32api")
            self.win32con = self.win32con or _module("win32con")
        self._last: tuple[int, int, str, str, str | None] | None = None

    def capability(self) -> ObserverCapability:
        available = all(
            module is not None
            for module in (self.win32gui, self.win32process, self.win32api, self.win32con)
        )
        return ObserverCapability(self.name, available)

    def poll(self) -> list[RawDeviceSignal]:
        if not self.capability().available:
            return []
        assert self.win32gui is not None
        assert self.win32process is not None
        assert self.win32api is not None
        assert self.win32con is not None
        hwnd = int(self.win32gui.GetForegroundWindow())
        if not hwnd:
            return []
        _thread_id, pid = self.win32process.GetWindowThreadProcessId(hwnd)
        pid = int(pid)
        title = str(self.win32gui.GetWindowText(hwnd) or "")
        window_class = str(self.win32gui.GetClassName(hwnd) or "unknown")
        path = _process_path(self.win32api, self.win32process, self.win32con, pid)
        process_name = _process_name(path, pid)
        current = (hwnd, pid, window_class, self._classify_title(title, window_class), path)
        if current == self._last:
            return []
        self._last = current
        base = {
            "process_name": process_name,
            "executable_path": path,
            "application_class": window_class,
            "window_class": window_class,
            "title_classification": current[3],
        }
        return [
            _signal("application.focused", self.name, base),
            _signal("window.focused", self.name, base),
            _signal("window.title_changed", self.name, base),
        ]

    @staticmethod
    def _classify_title(title: str, window_class: str) -> str:
        if not title:
            return "unknown"
        lowered = title.lower()
        if "password" in lowered or "sign in" in lowered or "login" in lowered:
            return "secure-dialog"
        if "dialog" in window_class.lower() or "#32770" in window_class:
            return "dialog"
        if "chrome" in window_class.lower() or "edge" in window_class.lower():
            return "browser"
        return "document"


class WindowsUIAutomationAdapter:
    name = "windows.uia"
    _CONTROL_TYPES: ClassVar[dict[int, str]] = {
        50000: "button",
        50002: "checkbox",
        50003: "combobox",
        50004: "edit",
        50005: "hyperlink",
        50006: "image",
        50007: "listitem",
        50011: "menuitem",
        50019: "tab",
        50020: "text",
        50024: "treeitem",
        50032: "window",
    }

    def __init__(self, *, use_native: bool = False, client_module: Any | None = None) -> None:
        self.client_module = client_module if use_native else None
        if use_native and self.client_module is None:
            self.client_module = _module("win32com.client")
        self._automation: Any | None = None
        self._last: tuple[str, str, str, bool] | None = None

    def capability(self) -> ObserverCapability:
        return ObserverCapability(self.name, self.client_module is not None)

    def _client(self) -> Any | None:
        if self.client_module is None:
            return None
        if self._automation is None:
            self._automation = self.client_module.Dispatch("UIAutomationClient.CUIAutomation8")
        return self._automation

    def focused_metadata(self) -> dict[str, Any] | None:
        client = self._client()
        if client is None:
            return None
        try:
            element = client.GetFocusedElement()
            control_id = int(element.CurrentControlType)
            control_type = self._CONTROL_TYPES.get(control_id, f"uia-{control_id}")
            class_name = str(element.CurrentClassName or "unknown")
            secure = bool(getattr(element, "CurrentIsPassword", False)) or (
                control_type == "edit" and "password" in class_name.lower()
            )
            metadata = {
                "control_type": control_type,
                "automation_id": str(element.CurrentAutomationId or "") or None,
                "class_name": class_name,
                "secure": secure,
            }
            if not secure and control_type not in {"edit", "text"}:
                metadata["name"] = str(element.CurrentName or "") or None
            return metadata
        except Exception:
            return None

    def secure_focus(self) -> bool:
        metadata = self.focused_metadata()
        return bool(metadata and metadata["secure"])

    def poll(self) -> list[RawDeviceSignal]:
        metadata = self.focused_metadata()
        if metadata is None:
            return []
        current = (
            str(metadata["control_type"]),
            str(metadata["automation_id"] or ""),
            str(metadata["class_name"]),
            bool(metadata["secure"]),
        )
        if current == self._last:
            return []
        self._last = current
        return [_signal("control.focused", self.name, metadata)]

    def invoke_focused_control(self, approved: bool = False) -> bool:
        if not approved:
            raise PermissionError("UI Automation invocation requires explicit approval")
        client = self._client()
        if client is None:
            return False
        try:
            element = client.GetFocusedElement()
            pattern = element.GetCurrentPattern(10000)
            pattern.Invoke()
            return True
        except Exception:
            return False


class _KbdHook(ctypes.Structure):
    _fields_ = [
        ("vk_code", ctypes.c_ulong),
        ("scan_code", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("extra", ctypes.c_void_p),
    ]


class _MouseHook(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
        ("mouse_data", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("extra", ctypes.c_void_p),
    ]


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class WindowsIdleAdapter:
    name = "windows.idle"

    def __init__(self, *, use_native: bool = False, idle_after_seconds: int = 60) -> None:
        self.enabled = use_native and sys.platform == "win32"
        self.idle_after_seconds = idle_after_seconds
        self._last_state: bool | None = None

    def capability(self) -> ObserverCapability:
        return ObserverCapability(self.name, self.enabled)

    def poll(self) -> list[RawDeviceSignal]:
        if not self.enabled:
            return []
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return []
        elapsed_ms = ctypes.windll.kernel32.GetTickCount() - int(info.dwTime)
        idle = elapsed_ms >= self.idle_after_seconds * 1000
        if idle == self._last_state:
            return []
        self._last_state = idle
        return [_signal("user.idle" if idle else "user.active", self.name, {})]


class WindowsInputHookAdapter:
    name = "windows.input"

    def __init__(
        self,
        *,
        use_native: bool = False,
        secure_focus: Callable[[], bool] | None = None,
        focused_control: Callable[[], dict[str, Any] | None] | None = None,
        emergency_stop: Callable[[], None] | None = None,
    ) -> None:
        self.enabled = use_native and sys.platform == "win32"
        self.secure_focus = secure_focus
        self.focused_control = focused_control
        self.emergency_stop = emergency_stop
        self._signals: deque[RawDeviceSignal] = deque(maxlen=256)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._keyboard_callback: Any = None
        self._mouse_callback: Any = None
        self._hook_handles: list[int] = []

    def capability(self) -> ObserverCapability:
        return ObserverCapability(self.name, self.enabled)

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._stop.clear()
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._pump, name="mllminal-windows-hooks", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=2)

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        self._thread.join(timeout=2)
        self._thread = None
        self._thread_id = 0

    def poll(self) -> list[RawDeviceSignal]:
        with self._lock:
            result = list(self._signals)
            self._signals.clear()
        return result

    def _queue(self, event_type: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._signals.append(_signal(event_type, self.name, payload))

    def _keyboard_event(self, vk: int) -> None:
        if self.secure_focus and self.secure_focus():
            return
        modifiers = self._modifiers()
        if vk == 0x1B and {"ctrl", "alt"} <= modifiers:
            if self.emergency_stop:
                self.emergency_stop()
            return
        names = {
            0x09: "tab",
            0x0D: "enter",
            0x1B: "escape",
            0x21: "page_up",
            0x22: "page_down",
            0x23: "end",
            0x24: "home",
            0x25: "left",
            0x26: "up",
            0x27: "right",
            0x28: "down",
        }
        if vk in {0x1B}:
            self._queue("keyboard.cancel", {"key_role": "cancel"})
        elif vk in {0x0D}:
            self._queue("keyboard.confirm", {"key_role": "confirm"})
        elif vk == 0x09:
            self._queue("keyboard.tab", {"key_role": "tab", "reverse": "shift" in modifiers})
        elif vk in names and vk not in {0x1B, 0x0D, 0x09}:
            self._queue(
                "keyboard.navigation",
                {"key_role": names[vk], "modifiers": sorted(modifiers)},
            )
        elif modifiers and 0x41 <= vk <= 0x5A:
            self._queue(
                "keyboard.shortcut",
                {"shortcut": "+".join([*sorted(modifiers), chr(vk).lower()])},
            )

    def _mouse_event(self, event_type: str, mouse_data: int = 0) -> None:
        if self.secure_focus and self.secure_focus():
            return
        if event_type == "mouse.scroll":
            delta = ctypes.c_short((mouse_data >> 16) & 0xFFFF).value
            payload: dict[str, Any] = {
                "direction": "up" if delta > 0 else "down",
                "amount_bucket": (
                    "small" if abs(delta) <= 120 else "medium" if abs(delta) <= 360 else "large"
                ),
            }
            self._queue(event_type, payload)
            return
        payload = {"button": "left"}
        if self.focused_control:
            control = self.focused_control()
            if control and not control.get("secure", False):
                payload.update(control)
                self._queue("control.invoked", payload)
                return
        self._queue(event_type, payload)

    def _modifiers(self) -> set[str]:
        user32 = ctypes.windll.user32
        values = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}
        return {name for name, vk in values.items() if user32.GetAsyncKeyState(vk) & 0x8000}

    def _pump(self) -> None:
        user32 = ctypes.windll.user32
        self._thread_id = int(ctypes.windll.kernel32.GetCurrentThreadId())
        hook_proc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p)

        def keyboard(n_code: int, w_param: int, l_param: int) -> int:
            if n_code >= 0 and w_param in (0x0100, 0x0104):
                self._keyboard_event(
                    int(ctypes.cast(l_param, ctypes.POINTER(_KbdHook)).contents.vk_code)
                )
            return int(user32.CallNextHookEx(0, n_code, w_param, l_param))

        def mouse(n_code: int, w_param: int, _l_param: int) -> int:
            if n_code >= 0:
                events = {
                    0x0201: "mouse.click",
                    0x0203: "mouse.double_click",
                    0x020A: "mouse.scroll",
                }
                if w_param in events:
                    mouse_data = int(
                        ctypes.cast(_l_param, ctypes.POINTER(_MouseHook)).contents.mouse_data
                    )
                    self._mouse_event(events[w_param], mouse_data)
            return int(user32.CallNextHookEx(0, n_code, w_param, _l_param))

        self._keyboard_callback = hook_proc(keyboard)
        self._mouse_callback = hook_proc(mouse)
        self._hook_handles = [
            int(user32.SetWindowsHookExW(13, self._keyboard_callback, 0, 0)),
            int(user32.SetWindowsHookExW(14, self._mouse_callback, 0, 0)),
        ]
        self._ready.set()
        msg = wintypes.MSG()
        while not self._stop.is_set() and user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        for handle in self._hook_handles:
            if handle:
                user32.UnhookWindowsHookEx(handle)
        self._hook_handles.clear()


class FakeWindowsAdapter:
    def __init__(self, name: str, batches: list[tuple[str, dict[str, Any]]]) -> None:
        self.name, self.batches = name, batches

    def capability(self) -> ObserverCapability:
        return ObserverCapability(self.name, True)

    def poll(self) -> list[RawDeviceSignal]:
        result: list[RawDeviceSignal] = []
        for kind, payload in self.batches:
            if kind == "process":
                result += [
                    _signal("application.started", self.name, {"process_name": name})
                    for name in payload.get("started", [])
                ]
                result += [
                    _signal("application.exited", self.name, {"process_name": name})
                    for name in payload.get("exited", [])
                ]
            elif kind == "foreground":
                safe = {key: value for key, value in payload.items() if key != "title"}
                result.append(_signal("application.focused", self.name, safe))
                if "title" in payload:
                    result.append(
                        _signal("window.title_changed", self.name, {**safe, "title": "redacted"})
                    )
            elif kind == "filesystem":
                result.append(
                    _signal(str(payload["event_type"]), self.name, {"process_name": "filesystem"})
                )
            elif kind == "idle":
                result.append(
                    _signal("user.idle" if payload.get("idle") else "user.active", self.name, {})
                )
        self.batches = []
        return result


def create_native_windows_adapters(
    emergency_stop: Callable[[], None] | None = None,
) -> list[Any]:
    """Build the real Windows observer stack; unavailable adapters remain inert."""
    uia = WindowsUIAutomationAdapter(use_native=True)
    return [
        WindowsProcessAdapter(use_native=True),
        WindowsForegroundAdapter(use_native=True),
        WindowsIdleAdapter(use_native=True),
        uia,
        WindowsInputHookAdapter(
            use_native=True,
            secure_focus=uia.secure_focus,
            focused_control=uia.focused_metadata,
            emergency_stop=emergency_stop,
        ),
    ]
