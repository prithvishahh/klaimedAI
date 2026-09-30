"""Alembic environment. Uses the migration (higher-privilege) DB role."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from rcm.core.config import get_settings

# Import models so Base.metadata is fully populated (incl. the Vector column).
from rcm.models import Base  # noqa: E402

target_metadata = Base.metadata


def _url() -> str:
    return get_settings().migration_database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    config_section = context.config.get_section(context.config.config_ini_section) or {}
    config_section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(
        config_section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
