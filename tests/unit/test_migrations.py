from pathlib import Path

from sqlalchemy import create_engine, inspect

from mllminal.migrations import upgrade_database


def test_alembic_upgrade_creates_versioned_runtime_schema(tmp_path: Path) -> None:
    database = tmp_path / "state.db"

    upgrade_database(database)

    tables = set(inspect(create_engine(f"sqlite:///{database}")).get_table_names())
    assert {"alembic_version", "sessions", "tasks", "approvals", "events"} <= tables
