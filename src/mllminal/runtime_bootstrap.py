"""Shared workspace and local-daemon bootstrap for user-facing commands."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from mllminal.client.api import DaemonClient
from mllminal.config import Settings
from mllminal.service_lifecycle import DaemonStartupError, ensure_daemon

ClientFactory = Callable[[Settings], Any]
EnsureDaemon = Callable[[Settings, ClientFactory], Awaitable[dict[str, Any]]]


class RuntimeBootstrapError(RuntimeError):
    """A product-level error raised before a command can use the local runtime."""

    def __init__(self, detail: str, *, diagnostics_path: Path | None = None) -> None:
        self.detail = detail
        self.diagnostics_path = diagnostics_path
        super().__init__(detail)


@dataclass(frozen=True)
class RuntimeContext:
    """The validated workspace and healthy daemon projection for one command."""

    settings: Settings
    workspace: Path
    health: dict[str, Any]
    started: bool


class RuntimeBootstrap:
    """Coordinate workspace validation and the existing authenticated daemon lifecycle."""

    def __init__(
        self,
        settings: Settings,
        client_factory: ClientFactory = DaemonClient,
        *,
        ensure_fn: EnsureDaemon = ensure_daemon,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._ensure_fn = ensure_fn

    def normalize_workspace(self, workspace: str | Path | None = None) -> Path:
        candidate = (
            Path(workspace).expanduser() if workspace is not None else self._settings.workspace_root
        )
        try:
            normalized = candidate.resolve(strict=False)
        except OSError as error:
            raise RuntimeBootstrapError(f"could not resolve workspace: {candidate}") from error
        if not normalized.exists():
            raise RuntimeBootstrapError(f"workspace does not exist: {normalized}")
        if not normalized.is_dir():
            raise RuntimeBootstrapError(f"workspace is not a directory: {normalized}")
        return normalized

    async def prepare(self, workspace: str | Path | None = None) -> RuntimeContext:
        normalized = self.normalize_workspace(workspace)
        runtime_settings = self._settings.model_copy(update={"workspace_root": normalized})
        try:
            ready = await self._ensure_fn(runtime_settings, self._client_factory)
        except DaemonStartupError as error:
            raise RuntimeBootstrapError(
                "MLLminal could not start its local service.\n"
                "Run `mllminal doctor` for diagnostics.",
                diagnostics_path=error.diagnostics_path,
            ) from None
        except (OSError, RuntimeError, TimeoutError, httpx.HTTPError) as error:
            raise RuntimeBootstrapError(
                "MLLminal could not start its local service.\n"
                "Run `mllminal doctor` for diagnostics."
            ) from error
        health = ready.get("health")
        return RuntimeContext(
            settings=runtime_settings,
            workspace=normalized,
            health=health if isinstance(health, dict) else {},
            started=isinstance(ready.get("started"), dict),
        )
