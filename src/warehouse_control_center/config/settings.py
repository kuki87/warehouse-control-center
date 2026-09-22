"""Typed settings with safe defaults and explicit test isolation."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Literal, Self, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.engine import URL

from warehouse_control_center.config.paths import RuntimePaths, resolve_runtime_paths
from warehouse_control_center.domain.exceptions import (
    UnsafeDatabasePathError,
    UnsafeRuntimePathError,
)

Environment = Literal["development", "test", "production"]


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated application configuration."""

    application_name: str
    environment: Environment
    runtime_root: Path
    database_path: Path
    log_directory: Path
    backup_directory: Path
    export_directory: Path
    timezone: str = "Europe/Sarajevo"
    sqlite_timeout_seconds: float = 30.0
    log_level: str = "INFO"
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 5

    def __post_init__(self) -> None:
        for field_name in (
            "runtime_root",
            "database_path",
            "log_directory",
            "backup_directory",
            "export_directory",
        ):
            path = getattr(self, field_name)
            object.__setattr__(self, field_name, path.expanduser().resolve())
        if not self.application_name.strip():
            raise ValueError("application_name must not be empty")
        if self.environment not in {"development", "test", "production"}:
            raise ValueError(f"Unsupported environment: {self.environment}")
        if not isfinite(self.sqlite_timeout_seconds) or self.sqlite_timeout_seconds <= 0:
            raise ValueError("sqlite_timeout_seconds must be positive")
        if self.log_max_bytes <= 0:
            raise ValueError("log_max_bytes must be positive")
        if self.log_backup_count <= 0:
            raise ValueError("log_backup_count must be positive")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone: {self.timezone}") from exc
        if self.environment == "test":
            _assert_isolated_test_paths(self)
        elif self.environment == "production":
            _assert_safe_production_paths(self)

    @property
    def database_url(self) -> URL:
        """Build a SQLAlchemy URL without manual path escaping."""
        return URL.create("sqlite+pysqlite", database=str(self.database_path))

    @property
    def runtime_paths(self) -> RuntimePaths:
        """Expose the configured locations as a cohesive value object."""
        return RuntimePaths(
            root=self.runtime_root,
            data=self.database_path.parent,
            logs=self.log_directory,
            backups=self.backup_directory,
            exports=self.export_directory,
        )

    @classmethod
    def load(cls) -> Self:
        """Load settings from environment variables and platform defaults."""
        application_name = os.getenv("WCC_APPLICATION_NAME", "Warehouse Control Center")
        environment = _parse_environment(os.getenv("WCC_ENVIRONMENT", "production"))
        root_value = os.getenv("WCC_RUNTIME_ROOT")
        paths = resolve_runtime_paths(
            application_name,
            root_override=Path(root_value) if root_value else None,
        )
        database_value = os.getenv("WCC_DATABASE_PATH")
        return cls(
            application_name=application_name,
            environment=environment,
            runtime_root=paths.root,
            database_path=(
                Path(database_value).expanduser().resolve() if database_value else paths.database
            ),
            log_directory=_environment_path("WCC_LOG_DIRECTORY", paths.logs),
            backup_directory=_environment_path("WCC_BACKUP_DIRECTORY", paths.backups),
            export_directory=_environment_path("WCC_EXPORT_DIRECTORY", paths.exports),
            timezone=os.getenv("WCC_TIMEZONE", "Europe/Sarajevo"),
            sqlite_timeout_seconds=float(os.getenv("WCC_SQLITE_TIMEOUT", "30")),
            log_level=os.getenv("WCC_LOG_LEVEL", "INFO").upper(),
            log_max_bytes=int(os.getenv("WCC_LOG_MAX_BYTES", str(5 * 1024 * 1024))),
            log_backup_count=int(os.getenv("WCC_LOG_BACKUP_COUNT", "5")),
        )

    @classmethod
    def for_testing(cls, root: Path) -> Self:
        """Construct settings whose writable state is isolated below ``root``."""
        paths = resolve_runtime_paths(root_override=root)
        return cls(
            application_name="Warehouse Control Center Tests",
            environment="test",
            runtime_root=paths.root,
            database_path=paths.database,
            log_directory=paths.logs,
            backup_directory=paths.backups,
            export_directory=paths.exports,
            timezone="UTC",
        )


def _assert_isolated_test_paths(settings: Settings) -> None:
    production_paths = resolve_runtime_paths("Warehouse Control Center")
    if _paths_overlap(settings.runtime_root, production_paths.root):
        raise UnsafeDatabasePathError("Tests may not use the production database path")
    _assert_writable_paths_below_root(settings, test_environment=True)


def _assert_safe_production_paths(settings: Settings) -> None:
    _assert_writable_paths_below_root(settings, test_environment=False)
    unsafe_roots = {Path(tempfile.gettempdir()).resolve(), *_installation_roots()}
    for unsafe_root in unsafe_roots:
        if _paths_overlap(settings.runtime_root, unsafe_root):
            raise UnsafeRuntimePathError(
                f"Production runtime root overlaps unsafe location: {unsafe_root}"
            )


def _assert_writable_paths_below_root(
    settings: Settings,
    *,
    test_environment: bool,
) -> None:
    writable_paths = (
        settings.database_path,
        settings.log_directory,
        settings.backup_directory,
        settings.export_directory,
    )
    if all(_is_strictly_below(path, settings.runtime_root) for path in writable_paths):
        return
    if test_environment:
        raise UnsafeDatabasePathError("Test writable paths must be located below the runtime root")
    raise UnsafeRuntimePathError("Production writable paths must be located below the runtime root")


def _installation_roots() -> set[Path]:
    source_file = Path(__file__).resolve()
    roots = {source_file.parents[2]}
    for start in (source_file.parent, Path.cwd().resolve()):
        for candidate in (start, *start.parents):
            if (candidate / ".git").exists() or (candidate / "pyproject.toml").is_file():
                roots.add(candidate.resolve())
                break
    return roots


def _is_strictly_below(path: Path, root: Path) -> bool:
    return root in path.parents


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _environment_path(variable: str, default: Path) -> Path:
    value = os.getenv(variable)
    return Path(value).expanduser().resolve() if value else default


def _parse_environment(value: str) -> Environment:
    normalized = value.strip().lower()
    if normalized not in {"development", "test", "production"}:
        raise ValueError(f"Unsupported environment: {value}")
    return cast(Environment, normalized)
