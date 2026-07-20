"""Authenticated local daemon client used by the thin desktop surface."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlencode

import httpx
from websockets.asyncio.client import connect

from mllminal.config import Settings


class DesktopState(StrEnum):
    DAEMON_UNAVAILABLE = "daemon unavailable"
    DAEMON_STARTING = "daemon starting"
    CONNECTED = "connected"
    AUTHENTICATION_FAILED = "authentication failed"
    OBSERVATION_PAUSED = "observation paused"
    EMERGENCY_STOP_ACTIVE = "emergency stop active"
    WORKFLOW_AWAITING_APPROVAL = "workflow awaiting approval"
    ACTION_EXECUTING = "action executing"
    VERIFICATION_FAILED = "verification failed"
    WORKER_UNAVAILABLE = "worker unavailable"


@dataclass(frozen=True)
class DesktopSnapshot:
    state: DesktopState
    status: dict[str, Any] = field(default_factory=dict)
    device: dict[str, Any] = field(default_factory=dict)
    privacy: dict[str, Any] = field(default_factory=dict)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    workflows: list[dict[str, Any]] = field(default_factory=list)
    permissions: list[dict[str, Any]] = field(default_factory=list)
    visual: dict[str, Any] | None = None
    error: str | None = None


class DaemonClient:
    """A stateless UI client; the daemon remains the only state owner."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.session_id: str | None = None

    @property
    def base_url(self) -> str:
        return self.settings.api_url

    def _token(self) -> str:
        try:
            return self.settings.token_path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise PermissionError("daemon authentication token is unavailable") from error

    async def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self._token()}"}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(base_url=self.base_url, timeout=8) as client:
            response = await client.request(method, path, json=payload, headers=headers)
        if response.status_code == 401:
            raise PermissionError("daemon authentication failed")
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, (dict, list)):
            raise RuntimeError("daemon returned an invalid response")
        return value

    async def snapshot(self) -> DesktopSnapshot:
        try:
            status = await self.request("GET", "/v1/status")
            device = await self.request("GET", "/v1/device/status")
            privacy = await self.request("GET", "/v1/privacy/status")
            tasks = await self.request("GET", "/v1/tasks")
            workflows = await self.request("GET", "/v1/workflows")
            permissions = await self.request("GET", "/v1/permissions")
            visual = await self.request("GET", "/v1/visual/latest")
        except PermissionError as error:
            return DesktopSnapshot(DesktopState.AUTHENTICATION_FAILED, error=str(error))
        except (httpx.ConnectError, httpx.TimeoutException) as error:
            return DesktopSnapshot(DesktopState.DAEMON_UNAVAILABLE, error=str(error))
        except (httpx.HTTPError, RuntimeError, OSError) as error:
            return DesktopSnapshot(DesktopState.WORKER_UNAVAILABLE, error=str(error))
        status_dict = _dict(status)
        device_dict = _dict(device)
        privacy_dict = _dict(privacy)
        task_list = _list(tasks)
        state = self._state(status_dict, device_dict, privacy_dict, task_list)
        return DesktopSnapshot(
            state=state,
            status=status_dict,
            device=device_dict,
            privacy=privacy_dict,
            tasks=task_list,
            workflows=_list(workflows),
            permissions=_list(permissions),
            visual=None if visual is None else _dict(visual),
        )

    async def ensure_session(self) -> str:
        if self.session_id is not None:
            return self.session_id
        result = await self.request(
            "POST",
            "/v1/sessions",
            {"workspace_root": str(self.settings.workspace_root.resolve())},
        )
        self.session_id = _dict(result)["id"]
        return self.session_id

    async def chat(self, content: str) -> dict[str, Any] | list[dict[str, Any]]:
        session_id = await self.ensure_session()
        return await self.request(
            "POST",
            f"/v1/sessions/{session_id}/messages",
            {"content": content},
            idempotency_key=f"desktop-message-{session_id}-{hash(content)}",
        )

    async def start_demonstration(self, label: str) -> dict[str, Any] | list[dict[str, Any]]:
        return await self.request(
            "POST",
            "/v1/demonstrate/start",
            {"label": label},
            idempotency_key=f"desktop-demonstrate-{label}",
        )

    async def pause_observation(self) -> dict[str, Any] | list[dict[str, Any]]:
        return await self.request(
            "POST",
            "/v1/privacy/pause",
            idempotency_key="desktop-pause-observation",
        )

    async def emergency_stop(self) -> dict[str, Any] | list[dict[str, Any]]:
        return await self.request(
            "POST",
            "/v1/privacy/emergency-stop",
            idempotency_key="desktop-emergency-stop",
        )

    async def stream_events(self, after_sequence: int = 0) -> Any:
        session_id = await self.ensure_session()
        query = urlencode({"session_id": session_id, "after_sequence": after_sequence})
        websocket_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        async with connect(f"{websocket_url}/v1/events?{query}") as socket:
            await socket.send(json.dumps({"type": "authenticate", "token": self._token()}))
            async for message in socket:
                yield json.loads(message)

    @staticmethod
    def _state(
        status: dict[str, Any],
        device: dict[str, Any],
        privacy: dict[str, Any],
        tasks: list[dict[str, Any]],
    ) -> DesktopState:
        if privacy.get("emergency_stop_active"):
            return DesktopState.EMERGENCY_STOP_ACTIVE
        if device.get("paused") or privacy.get("paused"):
            return DesktopState.OBSERVATION_PAUSED
        if any(str(task.get("state")) == "WAITING_FOR_APPROVAL" for task in tasks):
            return DesktopState.WORKFLOW_AWAITING_APPROVAL
        if any(str(task.get("state")) in {"EXECUTING", "VERIFYING"} for task in tasks):
            return DesktopState.ACTION_EXECUTING
        if any(str(task.get("state")) == "FAILED" for task in tasks):
            return DesktopState.VERIFICATION_FAILED
        if status.get("status") == "ok":
            return DesktopState.CONNECTED
        return DesktopState.WORKER_UNAVAILABLE


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
