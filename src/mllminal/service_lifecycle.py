"""Bounded local daemon process lifecycle helpers."""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from contextlib import suppress
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
    """Return the user-scoped ownership lock for the packaged daemon."""
    return settings.data_dir / "daemon.lock"


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
    if not isinstance(payload, dict) or not _same_executable(
        str(payload.get("executable", "")), executable
    ):
        return None
    raw_pid = payload.get("pid")
    if payload.get("status") == "starting":
        raw_pid = payload.get("owner_pid")
    try:
        pid = int(str(raw_pid))
    except (TypeError, ValueError):
        pid = 0
    if _process_is_alive(pid):
        return {"status": str(payload.get("status", "running")), "pid": pid}
    with suppress(FileNotFoundError, OSError):
        lock_path.unlink()
    return None


def daemon_status(settings: Settings) -> dict[str, Any]:
    """Return the local ownership projection without spawning a process."""
    executable = daemon_executable(settings)
    if executable is None:
        return {"status": "uninstalled"}
    info = _read_owned_lock(daemon_lock_path(settings), executable)
    return info or {"status": "stopped"}


def daemon_executable(settings: Settings) -> str | None:
    candidates = [
        shutil.which("mllminald"),
        str(
            settings.data_dir.parent.parent
            / "Programs"
            / "MLLminal"
            / "runtime"
            / "Scripts"
            / "mllminald.exe"
        ),
        str(settings.data_dir.parent / "app" / "runtime" / "Scripts" / "mllminald.exe"),
        str(Path(sys.executable).with_name("mllminald.exe")),
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
        return {"status": "already_running", "pid": existing["pid"]}

    lock_handle = None
    for _attempt in range(2):
        try:
            lock_handle = lock_path.open("x+", encoding="utf-8")
            json.dump(
                {"status": "starting", "owner_pid": os.getpid(), "executable": executable},
                lock_handle,
            )
            lock_handle.flush()
            break
        except FileExistsError:
            existing = _read_owned_lock(lock_path, executable)
            if existing is not None:
                return {"status": "already_running", "pid": existing["pid"]}
    if lock_handle is None:
        raise RuntimeError("another MLLminal daemon startup is already in progress")

    flags = 0
    breakaway_flag = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
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
        json.dump({"status": "running", "pid": process.pid, "executable": executable}, lock_handle)
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
