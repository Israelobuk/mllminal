"""Bounded local daemon process lifecycle helpers."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from mllminal.config import Settings

ClientFactory = Callable[[Settings], Any]


def daemon_executable(settings: Settings) -> str | None:
    candidates = [
        shutil.which("mllminald"),
        str(settings.data_dir.parent / "app" / "runtime" / "Scripts" / "mllminald.exe"),
        str(Path(sys.executable).with_name("mllminald.exe")),
    ]
    return next((item for item in candidates if item and Path(item).is_file()), None)


def start_daemon(settings: Settings) -> dict[str, Any]:
    executable = daemon_executable(settings)
    if executable is None:
        raise RuntimeError("installed mllminald executable was not found")
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    process = subprocess.Popen(
        [executable],
        cwd=str(settings.workspace_root),
        creationflags=flags,
        close_fds=True,
    )
    return {"status": "starting", "pid": process.pid}


async def ensure_daemon(
    settings: Settings,
    client_factory: ClientFactory | None = None,
    *,
    wait_seconds: float = 4.0,
) -> dict[str, Any]:
    """Return a healthy daemon projection, starting only the bounded daemon executable."""
    if client_factory is None:
        from mllminal.client.api import DaemonClient

        client_factory = DaemonClient
    client = client_factory(settings)
    try:
        health = await client.health()
        return {"status": "running", "health": health}
    except (OSError, RuntimeError, TimeoutError, httpx.HTTPError):
        started = start_daemon(settings)
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.1)
        try:
            health = await client.health()
        except (OSError, RuntimeError, TimeoutError, httpx.HTTPError):
            continue
        return {"status": "running", "health": health, "started": started}
    raise RuntimeError("mllminald did not become healthy after startup")
