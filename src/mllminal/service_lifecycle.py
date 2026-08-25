"""Bounded local daemon process lifecycle helpers."""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from mllminal.config import Settings

ClientFactory = Callable[[Settings], Any]


class DaemonStartupError(RuntimeError):
    """A bounded daemon startup attempt failed with a user-readable diagnostic."""

    def __init__(self, diagnostics_path: Path, detail: str) -> None:
        self.diagnostics_path = diagnostics_path
        self.detail = detail
        super().__init__(
            "MLLminal could not start its local service. Your files were not changed. "
            f"Choose Retry or Open Diagnostics: {diagnostics_path}. Detail: {detail}"
        )


def daemon_lock_path(settings: Settings) -> Path:
    """Return the legacy launcher ownership path for compatibility."""
    return daemon_startup_lock_path(settings)


def daemon_startup_lock_path(settings: Settings) -> Path:
    """Return the launcher metadata lock separate from the daemon runtime lock."""
    return settings.data_dir / "daemon-startup.lock"


def release_daemon_startup_lock(settings: Settings, pid: int | None = None) -> None:
    """Remove the launch marker only when it still belongs to this daemon."""
    path = daemon_startup_lock_path(settings)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
        return
    if not isinstance(payload, dict) or payload.get("status") not in {"starting", "running"}:
        return
    if pid is not None and _lock_pid(payload) != pid:
        return
    with suppress(FileNotFoundError, OSError):
        path.unlink()


def _diagnostics_path(settings: Settings) -> Path:
    return settings.data_dir.parent / "diagnostics" / "daemon-startup.log"


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        try:
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _process_start_identity(pid: int) -> str | None:
    """Return a stable process-start marker when the host exposes one."""
    if pid <= 0:
        return None
    if sys.platform == "win32":
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return None
        handle = windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None

        class FileTime(ctypes.Structure):
            _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

        creation = FileTime()
        exit_time = FileTime()
        kernel_time = FileTime()
        user_time = FileTime()
        try:
            if not windll.kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                return None
            value = (creation.high << 32) | creation.low
            return str(value)
        finally:
            windll.kernel32.CloseHandle(handle)

    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
    except (OSError, UnicodeError, IndexError):
        return None
    return fields[19] if len(fields) > 19 else None


def _process_executable(pid: int) -> str | None:
    """Return a process executable path when it can be queried safely."""
    if pid <= 0:
        return None
    if sys.platform == "win32":
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return None
        handle = windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        buffer = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_ulong(len(buffer))
        try:
            if not windll.kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                return None
            return buffer.value[: size.value]
        finally:
            windll.kernel32.CloseHandle(handle)
    try:
        return str(Path(f"/proc/{pid}/exe").resolve(strict=True))
    except OSError:
        return None


def _same_executable(left: str, right: str) -> bool:
    try:
        return (
            str(Path(left).resolve(strict=False)).casefold()
            == str(Path(right).resolve(strict=False)).casefold()
        )
    except OSError:
        return os.path.normcase(left) == os.path.normcase(right)


def _read_owned_lock(lock_path: Path, executable: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
        with suppress(FileNotFoundError, OSError):
            lock_path.unlink()
        return None
    if not isinstance(payload, dict):
        with suppress(FileNotFoundError, OSError):
            lock_path.unlink()
        return None
    pid = _lock_pid(payload)
    if not _same_executable(str(payload.get("executable", "")), executable):
        if not _process_is_alive(pid):
            with suppress(FileNotFoundError, OSError):
                lock_path.unlink()
            return None
        return {
            "status": "blocked",
            "pid": pid,
            "reason": "another process owns the daemon lock",
        }
    if _process_is_alive(pid):
        expected_start = payload.get("process_start_time")
        actual_start = _process_start_identity(pid) if expected_start is not None else None
        if (
            expected_start is not None
            and actual_start is not None
            and str(expected_start) != actual_start
        ):
            return {
                "status": "blocked",
                "pid": pid,
                "reason": "another process owns the daemon lock",
            }
        if payload.get("status") == "running":
            actual_executable = _process_executable(pid)
            if actual_executable is not None and not _same_executable(
                actual_executable, executable
            ):
                return {
                    "status": "blocked",
                    "pid": pid,
                    "reason": "another process owns the daemon lock",
                }
        return {"status": str(payload.get("status", "running")), "pid": pid}
    with suppress(FileNotFoundError, OSError):
        lock_path.unlink()
    return None


def _terminate_process_tree(pid: int) -> None:
    """Terminate one validated daemon process tree without opening a console window."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return
    os.kill(pid, signal.SIGTERM)


def stop_owned_daemon(settings: Settings, *, wait_seconds: float = 4.0) -> dict[str, Any]:
    """Stop only the daemon whose executable and process identity match our lock."""
    executable = daemon_executable(settings)
    if executable is None:
        return {"status": "already_stopped"}
    info = _read_owned_lock(daemon_lock_path(settings), executable)
    if info is None:
        return {"status": "already_stopped"}
    if info.get("status") == "blocked":
        raise RuntimeError(str(info.get("reason", "another process owns the daemon lock")))
    pid = int(info["pid"])
    _terminate_process_tree(pid)
    deadline = time.monotonic() + wait_seconds
    alive = _process_is_alive(pid)
    while alive and time.monotonic() < deadline:
        time.sleep(0.05)
        alive = _process_is_alive(pid)
    if alive:
        raise RuntimeError("owned mllminald process did not stop")
    release_daemon_startup_lock(settings, pid)
    return {"status": "stopped", "pid": pid}


def daemon_status(settings: Settings) -> dict[str, Any]:
    """Return the local ownership projection without spawning a process."""
    executable = daemon_executable(settings)
    if executable is None:
        return {"status": "uninstalled"}
    info = _read_owned_lock(daemon_lock_path(settings), executable)
    if info is not None and info.get("status") == "blocked":
        return {"status": "startup_blocked", **info}
    return info or {"status": "stopped"}


def daemon_executable(settings: Settings) -> str | None:
    candidates = [
        # Prefer the daemon shipped beside the running CLI so an isolated or
        # upgraded install cannot accidentally attach to another install on PATH.
        str(Path(sys.executable).with_name("mllminald.exe")),
        str(settings.data_dir.parent / "app" / "runtime" / "Scripts" / "mllminald.exe"),
        str(
            settings.data_dir.parent.parent
            / "Programs"
            / "MLLminal"
            / "runtime"
            / "Scripts"
            / "mllminald.exe"
        ),
        shutil.which("mllminald"),
    ]
    return next((item for item in candidates if item and Path(item).is_file()), None)


def start_daemon(settings: Settings) -> dict[str, Any]:
    executable = daemon_executable(settings)
    if executable is None:
        raise RuntimeError("installed mllminald executable was not found")
    lock_path = daemon_lock_path(settings)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_owned_lock(lock_path, executable)
    if existing is not None:
        if existing.get("status") == "blocked":
            raise RuntimeError(str(existing.get("reason", "another process owns the daemon lock")))
        return {"status": "already_running", "pid": existing["pid"]}

    lock_handle = None
    for _attempt in range(2):
        try:
            lock_handle = lock_path.open("x+", encoding="utf-8")
            json.dump(_lock_record("starting", executable, owner_pid=os.getpid()), lock_handle)
            lock_handle.flush()
            break
        except FileExistsError:
            existing = _read_owned_lock(lock_path, executable)
            if existing is not None:
                if existing.get("status") == "blocked":
                    raise RuntimeError(
                        str(existing.get("reason", "another process owns the daemon lock"))
                    ) from None
                return {"status": "already_running", "pid": existing["pid"]}
    if lock_handle is None:
        raise RuntimeError("another MLLminal daemon startup is already in progress")

    flags = 0
    breakaway_flag = 0
    if sys.platform == "win32":
        # CREATE_NO_WINDOW hides the console entry point without breaking
        # the bundled Python launcher.
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
        breakaway_flag = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        flags |= breakaway_flag
    try:

        def spawn(creationflags: int) -> subprocess.Popen[Any]:
            return subprocess.Popen(
                [executable],
                cwd=str(settings.workspace_root),
                creationflags=creationflags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )

        try:
            process = spawn(flags)
        except OSError:
            # Some hosts do not allow a child to break away from their job. Keep
            # normal user installs functional while preferring a true breakaway
            # for installer and CI-owned process trees.
            if not breakaway_flag:
                raise
            process = spawn(flags & ~breakaway_flag)
        lock_handle.seek(0)
        lock_handle.truncate()
        json.dump(_lock_record("running", executable, pid=process.pid), lock_handle)
        lock_handle.flush()
    except Exception:
        with suppress(FileNotFoundError, OSError):
            lock_path.unlink()
        raise
    finally:
        lock_handle.close()
    return {"status": "starting", "pid": process.pid}


def _write_startup_diagnostic(settings: Settings, detail: str) -> Path:
    path = _diagnostics_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{detail}\n")
    return path


async def ensure_daemon(
    settings: Settings,
    client_factory: ClientFactory | None = None,
    *,
    # Cold starts import the bundled ML stack; keep the wait bounded but usable on first launch.
    wait_seconds: float = 15.0,
) -> dict[str, Any]:
    """Return a healthy daemon projection after one bounded owned start attempt."""
    if client_factory is None:
        from mllminal.client.api import DaemonClient

        client_factory = DaemonClient
    client = client_factory(settings)
    try:
        health = await client.health()
        return {"status": "running", "health": health}
    except (OSError, RuntimeError, TimeoutError, httpx.HTTPError):
        try:
            started = start_daemon(settings)
        except (OSError, RuntimeError, TimeoutError) as error:
            if "another MLLminal daemon startup is already in progress" in str(error):
                started = {"status": "already_starting"}
            else:
                diagnostic = _write_startup_diagnostic(settings, str(error))
                raise DaemonStartupError(diagnostic, str(error)) from error
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.1)
        try:
            health = await client.health()
        except (OSError, RuntimeError, TimeoutError, httpx.HTTPError):
            continue
        return {"status": "running", "health": health, "started": started}
    if started.get("status") == "already_running":
        try:
            stop_owned_daemon(settings, wait_seconds=max(0.1, min(4.0, wait_seconds)))
            started = start_daemon(settings)
        except (OSError, RuntimeError, TimeoutError) as error:
            diagnostic = _write_startup_diagnostic(settings, str(error))
            raise DaemonStartupError(diagnostic, str(error)) from error
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.1)
            try:
                health = await client.health()
            except (OSError, RuntimeError, TimeoutError, httpx.HTTPError):
                continue
            return {"status": "running", "health": health, "started": started}
    detail = f"mllminald did not become healthy within {wait_seconds:.1f} seconds"
    diagnostic = _write_startup_diagnostic(settings, detail)
    raise DaemonStartupError(diagnostic, detail)


def _lock_pid(payload: dict[str, Any]) -> int:
    raw_pid = (
        payload.get("owner_pid") if payload.get("status") == "starting" else payload.get("pid")
    )
    try:
        return int(str(raw_pid))
    except (TypeError, ValueError):
        return 0


def _lock_record(
    status: str, executable: str, *, pid: int | None = None, owner_pid: int | None = None
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "status": status,
        "executable": executable,
    }
    identity_pid = pid if pid is not None else owner_pid
    if pid is not None:
        record["pid"] = pid
    if owner_pid is not None:
        record["owner_pid"] = owner_pid
    if identity_pid is not None:
        process_start_time = _process_start_identity(identity_pid)
        if process_start_time is not None:
            record["created_at"] = datetime.now(UTC).isoformat()
            record["process_start_time"] = process_start_time
    return record
