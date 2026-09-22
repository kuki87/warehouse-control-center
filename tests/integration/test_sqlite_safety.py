"""SQLite connections enforce the configured integrity pragmas."""

from sqlalchemy import Engine


def test_sqlite_safety_pragmas(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA synchronous").scalar_one() == 2
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 30_000


def test_every_simultaneous_connection_receives_safety_pragmas(engine: Engine) -> None:
    connections = [engine.connect() for _ in range(3)]
    try:
        for connection in connections:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
            assert connection.exec_driver_sql("PRAGMA synchronous").scalar_one() == 2
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 30_000
    finally:
        for connection in connections:
            connection.close()
