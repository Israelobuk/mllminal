from __future__ import annotations

import json
from pathlib import Path

from mllminal.config import ProviderConfig, ProviderConfigStore, Settings
from mllminal.install_lifecycle import InstallLifecycle
from mllminal.migrations import upgrade_database
from mllminal.runtime_store import RuntimeStore

PROJECT_ROOT = Path(__file__).parents[2]
UNINSTALL_SCRIPT = PROJECT_ROOT / "packaging" / "windows" / "uninstall.ps1"


def test_repair_preserves_durable_state_and_creates_backup(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    data_root = tmp_path / "data"
    backup_root = tmp_path / "backups"
    app_root.mkdir()
    settings = Settings(data_dir=data_root, workspace_root=tmp_path)
    settings.ensure_data_dir()
    upgrade_database(settings.database_path)

    store = RuntimeStore(settings.database_path)
    store.initialize()
    session = store.create_session(str(tmp_path))
    ProviderConfigStore(settings).save(ProviderConfig(model="preserved-model"))

    preserved_files = {
        "mil-sessions/session.json": '{"session":"preserved"}',
        "application-profiles/profile.json": '{"application":"demo"}',
        "learning/checkpoints/policy.pt": "checkpoint",
        "policy-bindings/active.json": '{"domain":"backend"}',
        "approvals/pending.json": '{"approval":"valid"}',
        "workflows/workflow.json": '{"workflow":"preserved"}',
        "execution-history/run.json": '{"run":"preserved"}',
        "settings.json": '{"theme":"dark"}',
    }
    for relative, value in preserved_files.items():
        path = data_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    manifest = data_root / "install-manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "custom_state": "preserved"}), encoding="utf-8"
    )
    lifecycle = InstallLifecycle(settings, app_root=app_root)
    result = lifecycle.repair()

    assert result["status"] == "repaired"
    assert result["backup"] is not None
    assert Path(result["backup"]).is_file()
    assert session.id == store.get_session(session.id).id
    assert ProviderConfigStore(settings).load().model == "preserved-model"
    assert json.loads(manifest.read_text(encoding="utf-8"))["custom_state"] == "preserved"
    for relative, value in preserved_files.items():
        assert (data_root / relative).read_text(encoding="utf-8") == value
    assert backup_root.is_dir()


def test_purge_requires_confirmation_and_never_touches_user_outputs(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    backup_root = tmp_path / "backups"
    app_root = tmp_path / "app"
    data_root.mkdir()
    backup_root.mkdir()
    app_root.mkdir()
    (data_root / "mllminal.db").write_text("local state", encoding="utf-8")
    (backup_root / "mllminal.db").write_text("backup", encoding="utf-8")
    outside_output = tmp_path / "report.pdf"
    outside_output.write_text("user output", encoding="utf-8")
    lifecycle = InstallLifecycle(Settings(data_dir=data_root), app_root=app_root)

    try:
        lifecycle.purge(None)
    except RuntimeError as error:
        assert "confirmation required" in str(error)
    else:
        raise AssertionError("purge must require exact confirmation")

    result = lifecycle.purge("MLLMINAL")
    assert result["status"] == "purged"
    assert not data_root.exists()
    assert not backup_root.exists()
    assert outside_output.read_text(encoding="utf-8") == "user output"


def test_uninstall_script_has_scoped_retention_and_cleanup_contract() -> None:
    script = UNINSTALL_SCRIPT.read_text(encoding="utf-8")
    assert "Stop-Process -Id" in script
    assert 'SetEnvironmentVariable("Path", ($keptPath -join ";"), "User")' in script
    assert "NativeMessagingHosts\\com.mllminal.bridge" in script
    assert "if ($deleteOwnedData)" in script
    assert "Refusing to delete an unscoped data directory" in script
    assert "User outputs were not touched" in script


def test_update_mode_preserves_state_and_rejects_unsafe_downgrade(tmp_path: Path) -> None:
    app_root = tmp_path / "Programs" / "MLLminal"
    data_root = tmp_path / "MLLminal" / "data"
    app_root.mkdir(parents=True)
    settings = Settings(data_dir=data_root, workspace_root=tmp_path)
    settings.ensure_data_dir()
    upgrade_database(settings.database_path)
    (data_root / "install-manifest.json").write_text(
        json.dumps({"version": "0.1.0", "policy_binding": "backend"}), encoding="utf-8"
    )
    marker = data_root / "workflows" / "preserved.json"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"workflow":"keep"}', encoding="utf-8")
    lifecycle = InstallLifecycle(settings)

    prepared = lifecycle.prepare_update("0.2.0")
    assert prepared["mode"] == "update"
    assert marker.read_text(encoding="utf-8") == '{"workflow":"keep"}'
    assert (
        json.loads((data_root / "install-manifest.json").read_text(encoding="utf-8"))[
            "policy_binding"
        ]
        == "backend"
    )

    try:
        lifecycle.install_mode("0.0.9")
    except RuntimeError as error:
        assert "downgrade" in str(error)
    else:
        raise AssertionError("unsafe downgrade was accepted")


def test_uninstall_contract_keeps_data_by_default_and_limits_purge_to_owned_roots() -> None:
    script = UNINSTALL_SCRIPT.read_text(encoding="utf-8-sig")

    assert "[switch]$Silent" in script
    assert "Also delete MLLminal local data" in script
    assert "Split-Path $DataDirectory -Leaf" in script
    assert "Remove-Item -LiteralPath $InstallRoot -Recurse -Force" in script
    assert 'GetFolderPath("Desktop")' in script
    assert "Startup" in script
