from pathlib import Path

from typer.testing import CliRunner

from mllminal.cli.main import create_app
from mllminal.config import Settings
from mllminal.install_lifecycle import InstallLifecycle, InstallLifecycleError
from mllminal.migrations import upgrade_database


def test_install_command_group_exposes_lifecycle_commands(tmp_path: Path) -> None:
    runner = CliRunner()
    app = create_app(Settings(data_dir=tmp_path, workspace_root=tmp_path))

    result = runner.invoke(app, ["install", "--help"])

    assert result.exit_code == 0
    assert "status" in result.stdout
    assert "repair" in result.stdout
    assert "data-path" in result.stdout
    assert "purge-data" in result.stdout


def test_install_status_supports_json_projection(tmp_path: Path) -> None:
    runner = CliRunner()
    app = create_app(Settings(data_dir=tmp_path, workspace_root=tmp_path))

    result = runner.invoke(app, ["install", "status", "--json"])

    assert result.exit_code == 0
    assert '"data_root"' in result.stdout
    assert '"app_root"' in result.stdout
    assert '"runtime_ready"' in result.stdout


def test_install_purge_requires_explicit_confirmation(tmp_path: Path) -> None:
    runner = CliRunner()
    data_root = tmp_path / "data"
    data_root.mkdir()
    app = create_app(Settings(data_dir=data_root, workspace_root=tmp_path))
    (data_root / "mllminal.db").write_text("owned state", encoding="utf-8")

    result = runner.invoke(app, ["install", "purge-data"])

    assert result.exit_code == 2
    assert "confirmation" in result.stdout.lower() or "confirmation" in result.stderr.lower()
    assert (data_root / "mllminal.db").exists()


def test_repair_backs_up_database_and_reaches_migration_head(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    app_root = tmp_path / "app"
    data_root.mkdir()
    app_root.mkdir()
    database = data_root / "mllminal.db"
    upgrade_database(database)
    before = database.read_bytes()
    lifecycle = InstallLifecycle(
        Settings(data_dir=data_root, workspace_root=tmp_path), app_root=app_root
    )

    result = lifecycle.repair()

    assert result["status"] == "repaired"
    assert result["backup"] is not None
    assert Path(result["backup"]).read_bytes() == before
    assert result["migration_after"] == result["migration_head"]


def test_repair_rejects_unknown_database_revision_without_mutation(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    app_root = tmp_path / "app"
    data_root.mkdir()
    app_root.mkdir()
    database = data_root / "mllminal.db"
    upgrade_database(database)
    from sqlalchemy import create_engine, text

    with create_engine(f"sqlite:///{database}").begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='future_revision'"))
    lifecycle = InstallLifecycle(
        Settings(data_dir=data_root, workspace_root=tmp_path), app_root=app_root
    )

    try:
        lifecycle.repair()
    except InstallLifecycleError as error:
        assert "unknown database revision" in str(error)
    else:
        raise AssertionError("repair accepted an unknown database revision")


def test_purge_with_confirmation_removes_owned_roots_only(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    outside = tmp_path / "user-report.pdf"
    outside.write_text("keep", encoding="utf-8")
    lifecycle = InstallLifecycle(Settings(data_dir=data_root, workspace_root=tmp_path))
    lifecycle.paths.backup_root.mkdir()
    (data_root / "mllminal.db").write_text("owned", encoding="utf-8")

    result = lifecycle.purge("MLLMINAL")

    assert result["status"] == "purged"
    assert not data_root.exists()
    assert not lifecycle.paths.backup_root.exists()
    assert outside.read_text(encoding="utf-8") == "keep"


def test_default_app_root_matches_one_click_install_location(tmp_path: Path) -> None:
    data_root = tmp_path / "MLLminal" / "data"
    lifecycle = InstallLifecycle(Settings(data_dir=data_root, workspace_root=tmp_path))

    assert lifecycle.paths.app_root == tmp_path / "Programs" / "MLLminal"


def test_install_mode_detects_fresh_repair_update_and_blocks_downgrade(tmp_path: Path) -> None:
    data_root = tmp_path / "MLLminal" / "data"
    app_root = tmp_path / "Programs" / "MLLminal"
    data_root.mkdir(parents=True)
    app_root.mkdir(parents=True)
    lifecycle = InstallLifecycle(Settings(data_dir=data_root, workspace_root=tmp_path))

    assert lifecycle.install_mode("0.1.0") == "fresh"
    (data_root / "install-manifest.json").write_text('{"version":"0.1.0"}', encoding="utf-8")

    assert lifecycle.install_mode("0.1.0") == "repair"
    assert lifecycle.install_mode("0.2.0") == "update"
    try:
        lifecycle.install_mode("0.0.9")
    except InstallLifecycleError as error:
        assert "downgrade" in str(error)
    else:
        raise AssertionError("unsafe downgrade was accepted")


def test_prepare_update_backups_database_before_replacement(tmp_path: Path) -> None:
    data_root = tmp_path / "MLLminal" / "data"
    app_root = tmp_path / "Programs" / "MLLminal"
    data_root.mkdir(parents=True)
    app_root.mkdir(parents=True)
    settings = Settings(data_dir=data_root, workspace_root=tmp_path)
    upgrade_database(settings.database_path)
    (data_root / "install-manifest.json").write_text('{"version":"0.1.0"}', encoding="utf-8")
    lifecycle = InstallLifecycle(settings)

    result = lifecycle.prepare_update("0.2.0")

    assert result["status"] == "update_prepared"
    assert result["mode"] == "update"
    assert result["backup"] is not None
    assert Path(result["backup"]).is_file()
