from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import inspect, text
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from agent_core.infrastructure.db.base import Base
from agent_core.infrastructure.db import models  # noqa: F401

config = context.config

database_url = os.getenv("AGENT_EDU_DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _ensure_version_column_capacity(connection) -> None:
    inspector = inspect(connection)
    if "alembic_version" not in inspector.get_table_names():
        return
    if connection.dialect.name == "postgresql":
        connection.execute(text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"))


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    _ensure_version_column_capacity(connection)
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio

    asyncio.run(run_migrations_online())
