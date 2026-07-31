import asyncio
from pathlib import Path
from types import MethodType

from mllminal.client.api import DaemonClient
from mllminal.config import Settings


def test_desktop_snapshot_projects_workflow_runs_from_daemon(tmp_path: Path) -> None:
    client = DaemonClient(Settings(data_dir=tmp_path, workspace_root=tmp_path))

    async def fake_request(
        _self: DaemonClient,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict | list[dict]:
        values: dict[str, dict | list[dict]] = {
            "/v1/status": {"status": "ok"},
            "/v1/device/status": {},
            "/v1/privacy/status": {},
            "/v1/tasks": [],
            "/v1/workflows": [],
            "/v1/workflow-runs": [{"id": "run-1", "state": "running"}],
            "/v1/permissions": [],
            "/v1/apps": [],
            "/v1/visual/latest": {},
            "/v1/suggestions": [],
            "/v1/suggestion-preferences": [],
            "/v1/adaptive/policy/status": {},
            "/v1/adaptive/verification-ranking/status": {},
            "/v1/adaptive/policies/status": {},
        }
        return values[path]

    client.request = MethodType(fake_request, client)
    snapshot = asyncio.run(client.snapshot())

    assert snapshot.workflow_runs == [{"id": "run-1", "state": "running"}]
