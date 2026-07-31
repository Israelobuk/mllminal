from pathlib import Path

import pytest

from mllminal.config import Settings
from mllminal.service_lifecycle import ensure_daemon


class FakeClient:
    def __init__(self, _settings: Settings) -> None:
        self.calls = 0

    async def health(self) -> dict[str, str]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("not running")
        return {"status": "ok", "daemon": "mllminald"}


@pytest.mark.asyncio
async def test_ensure_daemon_starts_once_then_waits_for_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[Path] = []

    def fake_start(settings: Settings) -> dict[str, object]:
        started.append(settings.data_dir)
        return {"status": "starting", "pid": 123}

    monkeypatch.setattr("mllminal.service_lifecycle.start_daemon", fake_start)
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)

    result = await ensure_daemon(settings, FakeClient, wait_seconds=0.5)

    assert result["status"] == "running"
    assert result["started"] == {"status": "starting", "pid": 123}
    assert started == [settings.data_dir]

def test_daemon_executable_uses_the_one_click_install_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mllminal.service_lifecycle import daemon_executable

    runtime_scripts = tmp_path / "Programs" / "MLLminal" / "runtime" / "Scripts"
    runtime_scripts.mkdir(parents=True)
    executable = runtime_scripts / "mllminald.exe"
    executable.write_text("", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "MLLminal" / "data", workspace_root=tmp_path)
    monkeypatch.setattr("mllminal.service_lifecycle.shutil.which", lambda _name: None)
    monkeypatch.setattr("mllminal.service_lifecycle.sys.executable", str(tmp_path / "python.exe"))

    assert daemon_executable(settings) == str(executable)