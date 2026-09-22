"""Runtime locations and production/test isolation safeguards."""

import os
from pathlib import Path

import pytest

from warehouse_control_center.config.paths import resolve_runtime_paths
from warehouse_control_center.config.settings import Settings
from warehouse_control_center.domain.exceptions import (
    UnsafeDatabasePathError,
    UnsafeRuntimePathError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_directories_are_created_below_override(tmp_path: Path) -> None:
    settings = Settings.for_testing(tmp_path)
    settings.runtime_paths.create()

    assert settings.database_path.parent == tmp_path.resolve() / "data"
    assert settings.log_directory == tmp_path.resolve() / "logs"
    assert settings.backup_directory == tmp_path.resolve() / "backups"
    assert settings.export_directory == tmp_path.resolve() / "exports"
    assert all(
        directory.is_dir()
        for directory in (
            settings.database_path.parent,
            settings.log_directory,
            settings.backup_directory,
            settings.export_directory,
        )
    )


def test_test_environment_refuses_production_database_path() -> None:
    production = resolve_runtime_paths("Warehouse Control Center")

    with pytest.raises(UnsafeDatabasePathError, match="production database"):
        Settings(
            application_name="Unsafe test",
            environment="test",
            runtime_root=production.root,
            database_path=production.database,
            log_directory=production.logs,
            backup_directory=production.backups,
            export_directory=production.exports,
            timezone="UTC",
        )


def test_test_database_must_be_below_runtime_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-test.db"

    with pytest.raises(UnsafeDatabasePathError, match="writable paths"):
        Settings(
            application_name="Unsafe test",
            environment="test",
            runtime_root=tmp_path,
            database_path=outside,
            log_directory=tmp_path / "logs",
            backup_directory=tmp_path / "backups",
            export_directory=tmp_path / "exports",
            timezone="UTC",
        )


def test_default_timezone_is_europe_sarajevo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WCC_ENVIRONMENT", "development")
    monkeypatch.setenv("WCC_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.delenv("WCC_TIMEZONE", raising=False)

    assert Settings.load().timezone == "Europe/Sarajevo"


def test_direct_paths_are_canonicalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        application_name="Development",
        environment="development",
        runtime_root=Path("runtime/child/.."),
        database_path=Path("runtime/data/warehouse.db"),
        log_directory=Path("runtime/logs"),
        backup_directory=Path("runtime/backups"),
        export_directory=Path("runtime/exports"),
    )

    assert settings.runtime_root == (tmp_path / "runtime").resolve()
    assert settings.database_path.is_absolute()


def test_all_test_writable_paths_must_be_isolated(tmp_path: Path) -> None:
    root = tmp_path / "runtime"

    with pytest.raises(UnsafeDatabasePathError, match="writable paths"):
        Settings(
            application_name="Unsafe test",
            environment="test",
            runtime_root=root,
            database_path=root / "data" / "warehouse.db",
            log_directory=root / "logs" / ".." / ".." / "outside-logs",
            backup_directory=root / "backups",
            export_directory=root / "exports",
            timezone="UTC",
        )


def test_production_runtime_must_not_use_temporary_directory(tmp_path: Path) -> None:
    root = tmp_path / "production"

    with pytest.raises(UnsafeRuntimePathError, match="unsafe location"):
        Settings(
            application_name="Unsafe production",
            environment="production",
            runtime_root=root,
            database_path=root / "data" / "warehouse.db",
            log_directory=root / "logs",
            backup_directory=root / "backups",
            export_directory=root / "exports",
        )


def test_production_runtime_must_not_use_repository_directory() -> None:
    root = PROJECT_ROOT / "runtime-data"

    with pytest.raises(UnsafeRuntimePathError, match="unsafe location"):
        Settings(
            application_name="Unsafe production",
            environment="production",
            runtime_root=root,
            database_path=root / "data" / "warehouse.db",
            log_directory=root / "logs",
            backup_directory=root / "backups",
            export_directory=root / "exports",
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows path comparison behavior")
def test_case_variant_of_production_path_is_still_rejected() -> None:
    production = resolve_runtime_paths("Warehouse Control Center")
    root = Path(str(production.root).swapcase())

    with pytest.raises(UnsafeDatabasePathError, match="production database"):
        Settings(
            application_name="Unsafe test",
            environment="test",
            runtime_root=root,
            database_path=Path(str(production.database).swapcase()),
            log_directory=root / "logs",
            backup_directory=root / "backups",
            export_directory=root / "exports",
            timezone="UTC",
        )


def test_symlink_to_production_path_is_rejected(tmp_path: Path) -> None:
    production = resolve_runtime_paths("Warehouse Control Center")
    link = tmp_path / "production-link"
    try:
        link.symlink_to(production.root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks unavailable: {exc}")

    with pytest.raises(UnsafeDatabasePathError, match="production database"):
        Settings(
            application_name="Unsafe test",
            environment="test",
            runtime_root=link,
            database_path=link / "data" / "warehouse.db",
            log_directory=link / "logs",
            backup_directory=link / "backups",
            export_directory=link / "exports",
            timezone="UTC",
        )


def test_non_finite_sqlite_timeout_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        Settings(
            application_name="Invalid timeout",
            environment="development",
            runtime_root=tmp_path,
            database_path=tmp_path / "data" / "warehouse.db",
            log_directory=tmp_path / "logs",
            backup_directory=tmp_path / "backups",
            export_directory=tmp_path / "exports",
            sqlite_timeout_seconds=float("nan"),
        )


def test_invalid_timezone_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown timezone"):
        Settings(
            application_name="Invalid timezone",
            environment="development",
            runtime_root=tmp_path,
            database_path=tmp_path / "data" / "warehouse.db",
            log_directory=tmp_path / "logs",
            backup_directory=tmp_path / "backups",
            export_directory=tmp_path / "exports",
            timezone="Europe/Not-A-Real-Zone",
        )


def test_zero_log_backups_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="log_backup_count must be positive"):
        Settings(
            application_name="Invalid rotation",
            environment="development",
            runtime_root=tmp_path,
            database_path=tmp_path / "data" / "warehouse.db",
            log_directory=tmp_path / "logs",
            backup_directory=tmp_path / "backups",
            export_directory=tmp_path / "exports",
            log_backup_count=0,
        )
