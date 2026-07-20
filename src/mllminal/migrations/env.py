from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import mllminal.workflow.persistence
import mllminal.activity.persistence
import mllminal.demonstration.persistence
import mllminal.interaction.persistence
import mllminal.privacy.persistence
import mllminal.runtime_store  # noqa: F401
from mllminal.persistence import Base

configuration = context.config
if configuration.config_file_name is not None:
    fileConfig(configuration.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=configuration.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        configuration.get_section(configuration.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
