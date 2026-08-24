from pathlib import Path

import pytest

from mllminal.config import Settings
from mllminal.service_lifecycle import ensure_daemon


def test_default_readiness_budget_covers_bundled_cold_start() -> None:
    import inspect

    parameter = inspect.signature(ensure_daemon).parameters["wait_seconds"]
    assert parameter.default == 15.0


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


def test_start_daemon_returns_already_running_for_a_live_owned_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import os

    from mllminal.service_lifecycle import daemon_lock_path, start_daemon

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    executable = tmp_path / "mllminald.exe"
    daemon_lock_path(settings).parent.mkdir(parents=True)
    daemon_lock_path(settings).write_text(
        json.dumps({"pid": os.getpid(), "executable": str(executable)}), encoding="utf-8"
    )

    def fake_daemon_executable(_settings: Settings) -> str:
        return str(executable)

    monkeypatch.setattr("mllminal.service_lifecycle.daemon_executable", fake_daemon_executable)
    monkeypatch.setattr(
        "mllminal.service_lifecycle.subprocess.Popen",
        lambda *_args, **_kwargs: pytest.fail("a live owned daemon must not be started twice"),
    )

    assert start_daemon(settings) == {"status": "already_running", "pid": os.getpid()}


def test_start_daemon_reclaims_stale_lock_and_records_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from mllminal.service_lifecycle import daemon_lock_path, start_daemon

    class FakeProcess:
        pid = 4567

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    executable = tmp_path / "mllminald.exe"
    daemon_lock_path(settings).parent.mkdir(parents=True)
    daemon_lock_path(settings).write_text(
        json.dumps({"pid": 1234, "executable": str(executable)}), encoding="utf-8"
    )

    def fake_daemon_executable(_settings: Settings) -> str:
        return str(executable)

    monkeypatch.setattr("mllminal.service_lifecycle.daemon_executable", fake_daemon_executable)
    monkeypatch.setattr("mllminal.service_lifecycle._process_is_alive", lambda _pid: False)
    monkeypatch.setattr(
        "mllminal.service_lifecycle.subprocess.Popen", lambda *_args, **_kwargs: FakeProcess()
    )

    result = start_daemon(settings)

    assert result == {"status": "starting", "pid": 4567}
    record = json.loads(daemon_lock_path(settings).read_text(encoding="utf-8"))
    assert record["status"] == "running"
    assert record["pid"] == 4567
    assert record["executable"] == str(executable)
    if "created_at" in record:
        assert isinstance(record["created_at"], str)
        assert isinstance(record["process_start_time"], str)


def test_start_daemon_detaches_stdio_from_the_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    from mllminal.service_lifecycle import start_daemon

    class FakeProcess:
        pid = 4567

    captured: dict[str, object] = {}
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    executable = tmp_path / "mllminald.exe"

    def fake_popen(*_args: object, **kwargs: object) -> FakeProcess:
        captured.update(kwargs)
        return FakeProcess()

    def fake_daemon_executable(_settings: Settings) -> str:
        return str(executable)

    monkeypatch.setattr("mllminal.service_lifecycle.daemon_executable", fake_daemon_executable)
    monkeypatch.setattr("mllminal.service_lifecycle._process_is_alive", lambda _pid: False)
    monkeypatch.setattr("mllminal.service_lifecycle.sys.platform", "win32")
    monkeypatch.setattr("mllminal.service_lifecycle.subprocess.Popen", fake_popen)

    start_daemon(settings)

    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["stdout"] is subprocess.DEVNULL
    assert captured["stderr"] is subprocess.DEVNULL
    assert captured["creationflags"] & subprocess.CREATE_BREAKAWAY_FROM_JOB


@pytest.mark.asyncio
async def test_ensure_daemon_reports_bounded_failure_with_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mllminal.service_lifecycle import DaemonStartupError, ensure_daemon

    class UnavailableClient:
        def __init__(self, _settings: Settings) -> None:
            pass

        async def health(self) -> dict[str, str]:
            raise RuntimeError("offline")

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    monkeypatch.setattr(
        "mllminal.service_lifecycle.start_daemon",
        lambda _settings: (_ for _ in ()).throw(RuntimeError("missing executable")),
    )

    with pytest.raises(DaemonStartupError) as error:
        await ensure_daemon(settings, UnavailableClient, wait_seconds=0.01)

    assert "Your files were not changed" in str(error.value)
    assert "Open Diagnostics" in str(error.value)
    assert error.value.diagnostics_path.is_file()
    assert "missing executable" in error.value.diagnostics_path.read_text(encoding="utf-8")


def test_start_daemon_reclaims_dead_lock_from_previous_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from mllminal.service_lifecycle import daemon_lock_path, start_daemon

    class FakeProcess:
        pid = 4568

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    current_executable = tmp_path / "current" / "mllminald.exe"
    old_executable = tmp_path / "old" / "mllminald.exe"
    daemon_lock_path(settings).parent.mkdir(parents=True)
    daemon_lock_path(settings).write_text(
        json.dumps(
            {
                "status": "running",
                "pid": 1234,
                "executable": str(old_executable),
                "created_at": "2026-08-22T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "mllminal.service_lifecycle.daemon_executable", lambda _settings: str(current_executable)
    )
    monkeypatch.setattr("mllminal.service_lifecycle._process_is_alive", lambda _pid: False)
    monkeypatch.setattr(
        "mllminal.service_lifecycle.subprocess.Popen", lambda *_args, **_kwargs: FakeProcess()
    )

    assert start_daemon(settings) == {"status": "starting", "pid": 4568}


def test_start_daemon_blocks_live_lock_owned_by_another_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import os

    from mllminal.service_lifecycle import daemon_lock_path, start_daemon

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    current_executable = tmp_path / "current" / "mllminald.exe"
    other_executable = tmp_path / "other" / "mllminald.exe"
    daemon_lock_path(settings).parent.mkdir(parents=True)
    daemon_lock_path(settings).write_text(
        json.dumps(
            {
                "status": "running",
                "pid": os.getpid(),
                "executable": str(other_executable),
                "created_at": "2026-08-22T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "mllminal.service_lifecycle.daemon_executable", lambda _settings: str(current_executable)
    )
    monkeypatch.setattr("mllminal.service_lifecycle._process_is_alive", lambda _pid: True)

    with pytest.raises(RuntimeError, match="owns the daemon lock"):
        start_daemon(settings)
    assert daemon_lock_path(settings).is_file()


def test_start_daemon_blocks_pid_reuse_when_process_identity_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import os

    from mllminal.service_lifecycle import daemon_lock_path, start_daemon

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    executable = tmp_path / "mllminald.exe"
    daemon_lock_path(settings).parent.mkdir(parents=True)
    daemon_lock_path(settings).write_text(
        json.dumps(
            {
                "status": "running",
                "pid": os.getpid(),
                "executable": str(executable),
                "process_start_time": "old-start",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "mllminal.service_lifecycle.daemon_executable", lambda _settings: str(executable)
    )
    monkeypatch.setattr("mllminal.service_lifecycle._process_is_alive", lambda _pid: True)
    monkeypatch.setattr(
        "mllminal.service_lifecycle._process_start_identity", lambda _pid: "new-start"
    )

    with pytest.raises(RuntimeError, match="owns the daemon lock"):
        start_daemon(settings)

def test_start_daemon_works_while_runtime_daemon_lock_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    import portalocker

    from mllminal.service_lifecycle import daemon_startup_lock_path, start_daemon

    class FakeProcess:
        pid = 4569

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    executable = tmp_path / "mllminald.exe"

    monkeypatch.setattr(
        "mllminal.service_lifecycle.daemon_executable", lambda _settings: str(executable)
    )
    monkeypatch.setattr(
        "mllminal.service_lifecycle.subprocess.Popen", lambda *_args, **_kwargs: FakeProcess()
    )

    with portalocker.Lock(settings.lock_path, mode="a", timeout=0):
        result = start_daemon(settings)

    assert result == {"status": "starting", "pid": 4569}
    startup_record = json.loads(
        daemon_startup_lock_path(settings).read_text(encoding="utf-8")
    )
    assert startup_record["status"] == "running"
    assert startup_record["pid"] == 4569
