"""Manual Alembic runner that works from source and installed wheels."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import as_file, files

from alembic import command
from alembic.config import Config

from warehouse_control_center.config.settings import Settings


@contextmanager
def alembic_config(settings: Settings) -> Iterator[Config]:
    """Build an Alembic config while packaged migration resources are available."""
    migration_resources = files("warehouse_control_center.migrations")
    with as_file(migration_resources) as script_location:
        config = Config()
        config.set_main_option("script_location", str(script_location))
        config.set_main_option(
            "sqlalchemy.url",
            settings.database_url.render_as_string(hide_password=False).replace("%", "%%"),
        )
        yield config


def upgrade_to_head(settings: Settings) -> None:
    """Apply all packaged migrations to an explicitly configured database."""
    settings.runtime_paths.create()
    with alembic_config(settings) as config:
        command.upgrade(config, "head")


def main() -> int:
    """Upgrade the configured database without starting the application."""
    upgrade_to_head(Settings.load())
    return 0
