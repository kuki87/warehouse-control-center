"""SQLite engine and short-lived session factory configuration."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from warehouse_control_center.config.settings import Settings

SessionFactory = sessionmaker[Session]


def create_sqlite_engine(settings: Settings, *, echo: bool = False) -> Engine:
    """Create a SQLite engine with integrity-oriented connection pragmas."""
    settings.runtime_paths.create()
    engine = create_engine(
        settings.database_url,
        connect_args={"timeout": settings.sqlite_timeout_seconds},
        echo=echo,
        pool_pre_ping=True,
    )
    timeout_ms = int(settings.sqlite_timeout_seconds * 1000)

    @event.listens_for(engine, "connect")
    def configure_sqlite_connection(dbapi_connection: Any, connection_record: Any) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {timeout_ms}")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = FULL")
        finally:
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> SessionFactory:
    """Build a factory; no Session instance is retained globally."""
    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
        close_resets_only=False,
    )
