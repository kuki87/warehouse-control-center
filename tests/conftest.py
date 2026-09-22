"""Top-level pytest fixtures; all writable state is rooted below ``tmp_path``."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from tests.fixtures.database import upgrade_to_head
from warehouse_control_center.config.settings import Settings
from warehouse_control_center.infrastructure.database.engine import (
    SessionFactory,
    create_session_factory,
    create_sqlite_engine,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings.for_testing(tmp_path)


@pytest.fixture
def migrated_settings(test_settings: Settings) -> Settings:
    test_settings.runtime_paths.create()
    upgrade_to_head(test_settings)
    return test_settings


@pytest.fixture
def engine(migrated_settings: Settings) -> Iterator[Engine]:
    database_engine = create_sqlite_engine(migrated_settings)
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> SessionFactory:
    return create_session_factory(engine)
