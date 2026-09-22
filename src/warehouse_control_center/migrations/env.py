"""Packaged Alembic migration environment."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from warehouse_control_center.config.settings import Settings
from warehouse_control_center.infrastructure.database import models  # noqa: F401
from warehouse_control_center.infrastructure.database.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if not config.get_main_option("sqlalchemy.url"):
    settings = Settings.load()
    settings.runtime_paths.create()
    config.set_main_option(
        "sqlalchemy.url",
        settings.database_url.render_as_string(hide_password=False).replace("%", "%%"),
    )

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        if is_sqlite:
            # SQLite cannot recreate a referenced table while FK enforcement is
            # enabled. Alembic batch migrations need this connection-local,
            # bounded exception; integrity is checked before enforcement is
            # restored below.
            connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
            # PRAGMA execution starts an implicit SQLAlchemy transaction. End it
            # before Alembic takes ownership of the migration transaction, or
            # the version-table insert can be rolled back while SQLite DDL remains.
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        try:
            with context.begin_transaction():
                context.run_migrations()
            if is_sqlite:
                violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
                if violations:
                    raise RuntimeError("Migration produced foreign-key violations")
                connection.commit()
        finally:
            if is_sqlite:
                if connection.in_transaction():
                    connection.rollback()
                connection.exec_driver_sql("PRAGMA foreign_keys = ON")
                connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
