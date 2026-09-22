"""Bootstrap fails closed when runtime resources or schema state are unusable."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from tests.fixtures.database import upgrade_to_head
from warehouse_control_center.bootstrap import bootstrap
from warehouse_control_center.config.settings import Settings
from warehouse_control_center.domain.exceptions import DatabaseSchemaError
from warehouse_control_center.main import main


def test_bootstrap_rejects_missing_schema(test_settings: Settings) -> None:
    with pytest.raises(DatabaseSchemaError, match="not initialized"):
        bootstrap(test_settings)


def test_bootstrap_accepts_current_schema_and_logs_lifecycle(
    migrated_settings: Settings,
) -> None:
    resources = bootstrap(migrated_settings)
    resources.shutdown()

    content = (migrated_settings.log_directory / "app.log").read_text(encoding="utf-8")
    assert "Warehouse Control Center startup" in content
    assert "Database connectivity verified" in content
    assert "Database schema verified" in content
    assert "Warehouse Control Center shutdown complete" in content


def test_bootstrap_rejects_outdated_schema(migrated_settings: Settings) -> None:
    engine = create_engine(migrated_settings.database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = '0000_previous'"))
    finally:
        engine.dispose()

    with pytest.raises(DatabaseSchemaError, match="0000_previous"):
        bootstrap(migrated_settings)


def test_bootstrap_rejects_unexpected_revision(test_settings: Settings) -> None:
    test_settings.runtime_paths.create()
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES ('future_branch')")
            )
    finally:
        engine.dispose()

    with pytest.raises(DatabaseSchemaError, match="future_branch"):
        bootstrap(test_settings)


def test_bootstrap_rejects_schema_that_claims_head_but_is_incomplete(
    migrated_settings: Settings,
) -> None:
    engine = create_engine(migrated_settings.database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE audit_events"))
    finally:
        engine.dispose()

    with pytest.raises(DatabaseSchemaError, match="missing: audit_events"):
        bootstrap(migrated_settings)


def test_bootstrap_fails_when_database_path_is_a_directory(test_settings: Settings) -> None:
    test_settings.database_path.mkdir(parents=True)

    with pytest.raises(OperationalError):
        bootstrap(test_settings)


def test_bootstrap_fails_when_database_parent_cannot_be_created(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    blocked_parent = root / "blocked"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    settings = Settings(
        application_name="Blocked database",
        environment="test",
        runtime_root=root,
        database_path=blocked_parent / "warehouse.db",
        log_directory=root / "logs",
        backup_directory=root / "backups",
        export_directory=root / "exports",
        timezone="UTC",
    )

    with pytest.raises((FileExistsError, NotADirectoryError)):
        bootstrap(settings)


def test_bootstrap_fails_when_log_directory_is_a_file(tmp_path: Path) -> None:
    settings = Settings.for_testing(tmp_path)
    settings.runtime_root.mkdir(parents=True, exist_ok=True)
    settings.log_directory.write_text("not a directory", encoding="utf-8")

    with pytest.raises(FileExistsError):
        bootstrap(settings)


def test_main_returns_failure_and_logs_schema_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "runtime"
    monkeypatch.setenv("WCC_ENVIRONMENT", "test")
    monkeypatch.setenv("WCC_RUNTIME_ROOT", str(root))

    shown: list[BaseException] = []
    monkeypatch.setattr(
        "warehouse_control_center.main.show_startup_error",
        lambda error: shown.append(error),
    )

    assert main() == 1
    assert len(shown) == 1
    assert isinstance(shown[0], DatabaseSchemaError)
    content = (root / "logs" / "app.log").read_text(encoding="utf-8")
    assert "Application startup failed" in content
    assert "Traceback (most recent call last)" in content


def test_main_success_smoke_test(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "runtime"
    monkeypatch.setenv("WCC_ENVIRONMENT", "test")
    monkeypatch.setenv("WCC_RUNTIME_ROOT", str(root))
    settings = Settings.load()
    settings.runtime_paths.create()
    upgrade_to_head(settings)

    initial_passwords: list[str | None] = []

    def fake_qt_run(resources: object) -> int:
        initial = resources.initial_administrator  # type: ignore[attr-defined]
        initial_passwords.append(initial.take_temporary_password() if initial is not None else None)
        resources.shutdown()  # type: ignore[attr-defined]
        return 0

    monkeypatch.setattr("warehouse_control_center.main.run_qt_application", fake_qt_run)

    assert main() == 0
    temporary_password = initial_passwords[0]
    assert temporary_password is not None
    assert len(temporary_password) == 24
    content = (root / "logs" / "app.log").read_text(encoding="utf-8")
    assert temporary_password not in content
    assert "Database schema verified" in content
    assert "Warehouse Control Center shutdown complete" in content

    assert main() == 0
    assert initial_passwords == [temporary_password, None]
