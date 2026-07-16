from pathlib import Path

from mllminal.config import Settings


def test_settings_create_portable_app_paths(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, workspace_root=tmp_path / "workspace")

    assert settings.database_path == tmp_path / "mllminal.db"
    assert settings.token_path == tmp_path / "token"
    assert settings.pid_path == tmp_path / "daemon.json"
    assert settings.lock_path == tmp_path / "daemon.lock"
    assert settings.api_url == "http://127.0.0.1:7337"
