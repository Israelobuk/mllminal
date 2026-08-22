from pathlib import Path

import pytest

from mllminal.config import Settings
from mllminal.runtime_bootstrap import RuntimeBootstrap, RuntimeBootstrapError


@pytest.mark.asyncio
async def test_bootstrap_normalizes_workspace_and_waits_for_daemon(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls: list[Path] = []

    async def fake_ensure(settings: Settings, _factory: object) -> dict[str, object]:
        calls.append(settings.workspace_root)
        return {"status": "running", "health": {"status": "ok"}}

    bootstrap = RuntimeBootstrap(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path),
        lambda _settings: object(),
        ensure_fn=fake_ensure,
    )

    result = await bootstrap.prepare(workspace / ".")

    assert result.workspace == workspace.resolve()
    assert result.settings.workspace_root == workspace.resolve()
    assert result.health == {"status": "ok"}
    assert calls == [workspace.resolve()]


def test_bootstrap_rejects_missing_workspace(tmp_path: Path) -> None:
    bootstrap = RuntimeBootstrap(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path),
        lambda _settings: object(),
    )

    with pytest.raises(RuntimeBootstrapError, match="workspace does not exist"):
        bootstrap.normalize_workspace(tmp_path / "missing")
