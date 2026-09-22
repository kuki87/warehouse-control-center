"""Potentially blocking operations use isolated sessions outside the GUI thread."""

from __future__ import annotations

import gc
from threading import get_ident
from weakref import ref

from PySide6.QtCore import QThread, QThreadPool
from pytestqt.qtbot import QtBot
from sqlalchemy.orm import Session

from warehouse_control_center.application.dto import SessionContext
from warehouse_control_center.application.services import (
    AuthenticationService,
    FirstRunAdministratorService,
)
from warehouse_control_center.infrastructure.clock import UtcClock
from warehouse_control_center.infrastructure.database.engine import SessionFactory
from warehouse_control_center.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from warehouse_control_center.infrastructure.security import (
    Argon2PasswordHasher,
    SecureTemporaryPasswordGenerator,
)
from warehouse_control_center.presentation.qt.workers import DatabaseTaskRunner


def test_database_worker_success_runs_off_gui_thread(qtbot: QtBot) -> None:
    pool = QThreadPool()
    runner = DatabaseTaskRunner(pool)
    gui_thread = QThread.currentThread()
    results: list[tuple[QThread, str]] = []
    callback_threads: list[QThread] = []
    errors: list[BaseException] = []

    def receive(result: tuple[QThread, str]) -> None:
        callback_threads.append(QThread.currentThread())
        results.append(result)

    runner.submit(
        lambda: (QThread.currentThread(), "complete"),
        on_result=receive,
        on_error=errors.append,
    )

    qtbot.waitUntil(lambda: bool(results), timeout=3_000)
    assert errors == []
    assert results[0][0] is not gui_thread
    assert results[0][1] == "complete"
    assert callback_threads == [gui_thread]
    assert pool.waitForDone(3_000)


def test_database_worker_emits_controlled_failure(qtbot: QtBot) -> None:
    pool = QThreadPool()
    runner = DatabaseTaskRunner(pool)
    gui_thread = QThread.currentThread()
    errors: list[BaseException] = []
    callback_threads: list[QThread] = []

    def fail() -> object:
        raise RuntimeError("worker failure")

    def receive_error(error: BaseException) -> None:
        callback_threads.append(QThread.currentThread())
        errors.append(error)

    runner.submit(fail, on_result=lambda result: None, on_error=receive_error)

    qtbot.waitUntil(lambda: bool(errors), timeout=3_000)
    assert isinstance(errors[0], RuntimeError)
    assert callback_threads == [gui_thread]
    assert pool.waitForDone(3_000)


def test_database_worker_releases_sensitive_operation_after_completion(qtbot: QtBot) -> None:
    class SensitiveInput:
        pass

    pool = QThreadPool()
    runner = DatabaseTaskRunner(pool)
    sensitive_input = SensitiveInput()
    retained = ref(sensitive_input)

    def operation(value: SensitiveInput = sensitive_input) -> str:
        del value
        return "complete"

    completed: list[str] = []
    worker = runner.submit(
        operation,
        on_result=completed.append,
        on_error=lambda error: None,
    )
    del operation, sensitive_input
    qtbot.waitUntil(lambda: bool(completed), timeout=3_000)
    assert pool.waitForDone(3_000)
    gc.collect()

    assert worker not in runner._workers
    assert retained() is None


def test_real_service_creates_and_closes_session_inside_worker(
    qtbot: QtBot,
    session_factory: SessionFactory,
) -> None:
    gui_thread_id = get_ident()
    session_threads: list[int] = []
    sessions: list[Session] = []
    units_of_work: list[SqlAlchemyUnitOfWork] = []

    class TrackingUnitOfWork(SqlAlchemyUnitOfWork):
        def __enter__(self) -> TrackingUnitOfWork:
            entered = super().__enter__()
            session_threads.append(get_ident())
            sessions.append(entered.session)
            return self

    def uow_factory() -> SqlAlchemyUnitOfWork:
        unit = TrackingUnitOfWork(session_factory)
        units_of_work.append(unit)
        return unit

    clock = UtcClock()
    hasher = Argon2PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    first_run = FirstRunAdministratorService(
        uow_factory,
        hasher,
        SecureTemporaryPasswordGenerator(),
        clock,
    )
    authentication = AuthenticationService(uow_factory, hasher, clock)
    credential = first_run.initialize()
    assert credential is not None
    temporary_secret = credential.take_temporary_password()

    pool = QThreadPool()
    runner = DatabaseTaskRunner(pool)
    results: list[tuple[int, SessionContext]] = []
    callback_thread_ids: list[int] = []
    errors: list[BaseException] = []

    def operation() -> tuple[int, SessionContext]:
        return get_ident(), authentication.login("admin", temporary_secret)

    def receive(result: tuple[int, SessionContext]) -> None:
        callback_thread_ids.append(get_ident())
        results.append(result)

    runner.submit(operation, on_result=receive, on_error=errors.append)
    qtbot.waitUntil(lambda: bool(results) or bool(errors), timeout=5_000)

    assert errors == []
    worker_thread_id, session = results[0]
    assert session.username == "admin"
    assert worker_thread_id != gui_thread_id
    assert callback_thread_ids == [gui_thread_id]
    assert session_threads == [gui_thread_id, worker_thread_id]
    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    assert all(unit.closed for unit in units_of_work)
    assert pool.waitForDone(3_000)
