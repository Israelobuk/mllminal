"""Programmatic Alembic migration entry point."""

from pathlib import Path

from alembic import command
from alembic.config import Config


def upgrade_database(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    configuration = Config()
    configuration.set_main_option("script_location", str(Path(__file__).parent))
    configuration.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    command.upgrade(configuration, "head")
