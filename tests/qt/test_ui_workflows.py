"""Headless production-path tests for authentication and user administration UI."""

from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QObject, Qt, QThreadPool
from PySide6.QtWidgets import QApplication, QPushButton
from pytestqt.qtbot import QtBot

from warehouse_control_center.application.dto import SessionContext, TemporaryCredential, UserDTO
from warehouse_control_center.domain.enums import UserRole
from warehouse_control_center.domain.exceptions import AuthenticationError, DatabaseBusyError
from warehouse_control_center.presentation.qt.application import DesktopApplication
from warehouse_control_center.presentation.qt.dialogs.confirm_dialog import ConfirmDialog
from warehouse_control_center.presentation.qt.dialogs.create_user_dialog import CreateUserDialog
from warehouse_control_center.presentation.qt.dialogs.password_change_dialog import (
    PasswordChangeDialog,
)
from warehouse_control_center.presentation.qt.dialogs.reset_password_dialog import (
    ResetPasswordDialog,
)
from warehouse_control_center.presentation.qt.dialogs.temporary_credential_dialog import (
    FirstRunDialog,
    TemporaryCredentialDialog,
)
from warehouse_control_center.presentation.qt.pages.users_page import UsersPage
from warehouse_control_center.presentation.qt.windows.login_window import LoginWindow
from warehouse_control_center.presentation.qt.windows.main_window import MainWindow


def _session(role: UserRole = UserRole.ADMIN, *, must_change: bool = False) -> SessionContext:
    return SessionContext(
        1,
        "admin" if role is UserRole.ADMIN else "warehouse-user",
        role,
        datetime(2026, 1, 1, tzinfo=UTC),
        must_change,
    )


def _user(
    user_id: int,
    username: str,
    role: UserRole,
    *,
    active: bool = True,
    must_change: bool = False,
) -> UserDTO:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return UserDTO(
        id=user_id,
        username=username,
        role=role,
        active=active,
        must_change_password=must_change,
        failed_login_attempts=0,
        locked_until=None,
        created_at=now,
        updated_at=now,
        archived_at=None,
    )


def _credential(user: UserDTO, value: str = "temporary-password-value") -> TemporaryCredential:
    return TemporaryCredential(user, value)


def _logger() -> logging.Logger:
    logger = logging.getLogger(f"warehouse_control_center.ui.tests.{id(object())}")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    return logger


class FakeAuthentication:
    def __init__(self, login_result: SessionContext | BaseException) -> None:
        self.login_result = login_result
        self.change_result: SessionContext | BaseException = _session()
        self.login_calls: list[tuple[str, str]] = []
        self.change_calls: list[tuple[SessionContext, str, str]] = []
        self.logout_calls: list[SessionContext] = []

    def login(self, username: str, secret: str) -> SessionContext:
        self.login_calls.append((username, secret))
        if isinstance(self.login_result, BaseException):
            raise self.login_result
        return self.login_result

    def change_password(
        self,
        session: SessionContext,
        current: str,
        new: str,
    ) -> SessionContext:
        self.change_calls.append((session, current, new))
        if isinstance(self.change_result, BaseException):
            raise self.change_result
        return self.change_result

    def logout(self, session: SessionContext) -> None:
        self.logout_calls.append(session)


class FakeUsers:
    def __init__(self) -> None:
        self.records = [
            _user(1, "admin", UserRole.ADMIN),
            _user(2, "operator", UserRole.WAREHOUSE_OPERATOR),
        ]
        self.created: list[tuple[str, UserRole]] = []
        self.reset: list[int] = []

    def list_users(
        self,
        session: SessionContext,
        *,
        search: str | None = None,
        include_archived: bool = False,
    ) -> list[UserDTO]:
        del session, search, include_archived
        return list(self.records)

    def create_user(
        self,
        session: SessionContext,
        username: str,
        role: UserRole,
    ) -> TemporaryCredential:
        del session
        self.created.append((username, role))
        user = _user(3, username, role, must_change=True)
        self.records.append(user)
        return _credential(user, "created-user-secret")

    def reset_password(self, session: SessionContext, user_id: int) -> TemporaryCredential:
        del session
        self.reset.append(user_id)
        user = next(record for record in self.records if record.id == user_id)
        return _credential(user, "reset-user-secret")

    def change_role(self, session: SessionContext, user_id: int, role: UserRole) -> UserDTO:
        del session
        return self._replace(user_id, role=role)

    def activate_user(self, session: SessionContext, user_id: int) -> UserDTO:
        del session
        return self._replace(user_id, active=True)

    def deactivate_user(self, session: SessionContext, user_id: int) -> UserDTO:
        del session
        return self._replace(user_id, active=False)

    def archive_user(self, session: SessionContext, user_id: int) -> UserDTO:
        del session
        return next(record for record in self.records if record.id == user_id)

    def restore_user(self, session: SessionContext, user_id: int) -> UserDTO:
        del session
        return next(record for record in self.records if record.id == user_id)

    def _replace(
        self,
        user_id: int,
        *,
        role: UserRole | None = None,
        active: bool | None = None,
    ) -> UserDTO:
        old = next(record for record in self.records if record.id == user_id)
        replacement = UserDTO(
            id=old.id,
            username=old.username,
            role=role or old.role,
            active=old.active if active is None else active,
            must_change_password=old.must_change_password,
            failed_login_attempts=old.failed_login_attempts,
            locked_until=old.locked_until,
            created_at=old.created_at,
            updated_at=old.updated_at,
            archived_at=old.archived_at,
        )
        self.records[self.records.index(old)] = replacement
        return replacement


@dataclass
class FakeResources:
    authentication: FakeAuthentication
    users: FakeUsers
    logger: logging.Logger
    initial_administrator: TemporaryCredential | None = None
    shutdown_called: bool = False

    def shutdown(self) -> None:
        self.shutdown_called = True


@pytest.fixture
def thread_pool() -> QThreadPool:
    pool = QThreadPool()
    pool.setMaxThreadCount(2)
    yield pool
    assert pool.waitForDone(5_000)


def test_login_window_opens_and_enter_submits(
    qtbot: QtBot,
    thread_pool: QThreadPool,
) -> None:
    authentication = FakeAuthentication(_session())
    window = LoginWindow(cast("object", authentication), thread_pool, _logger())
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()
    window.username_input.setText("admin")
    window.secret_input.setText("valid-password")

    with qtbot.waitSignal(window.authenticated, timeout=3_000):
        qtbot.keyPress(window.secret_input, Qt.Key.Key_Return)

    assert authentication.login_calls == [("admin", "valid-password")]
    assert window.secret_input.text() == ""


def test_wrong_password_and_database_busy_remain_safe_on_login(
    qtbot: QtBot,
    thread_pool: QThreadPool,
) -> None:
    authentication = FakeAuthentication(AuthenticationError("internal state"))
    window = LoginWindow(cast("object", authentication), thread_pool, _logger())
    qtbot.addWidget(window)
    window.show()
    window.username_input.setText("admin")
    window.secret_input.setText("wrong-password")
    qtbot.mouseClick(window.login_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.status.isVisible(), timeout=3_000)
    assert window.status.message == "Invalid username or password."
    assert "internal state" not in window.status.message
    assert window.isVisible()

    authentication.login_result = DatabaseBusyError("database is locked")
    window.secret_input.setText("another-password")
    qtbot.mouseClick(window.login_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "busy" in window.status.message.casefold(), timeout=3_000)
    assert "locked" not in window.status.message.casefold()


def test_first_run_credential_is_shown_once_and_cleared(qtbot: QtBot) -> None:
    credential = _credential(_user(1, "admin", UserRole.ADMIN), "first-run-secret")
    dialog = FirstRunDialog(credential)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.credential_value.text() == "first-run-secret"
    qtbot.mouseClick(dialog.copy_button, Qt.MouseButton.LeftButton)
    assert QApplication.clipboard().text() == "first-run-secret"
    dialog.accept()
    assert dialog.credential_value.text() == ""


def test_mandatory_password_change_cannot_be_bypassed_and_cancel_returns_to_login(
    qtbot: QtBot,
    qapp: QApplication,
) -> None:
    authentication = FakeAuthentication(_session(must_change=True))
    resources = FakeResources(authentication, FakeUsers(), _logger())
    controller = DesktopApplication(qapp, cast("object", resources))
    controller.start()
    controller.login_window.username_input.setText("admin")
    controller.login_window.secret_input.setText("temporary-secret")
    qtbot.mouseClick(controller.login_window.login_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: controller.password_dialog is not None and controller.password_dialog.isVisible(),
        timeout=3_000,
    )
    assert controller.main_window is None
    assert not controller.login_window.isVisible()
    cast(PasswordChangeDialog, controller.password_dialog).reject()
    qtbot.waitUntil(controller.login_window.isVisible, timeout=3_000)
    assert controller.main_window is None
    controller.shutdown()


def test_password_change_success_opens_main_window(
    qtbot: QtBot,
    qapp: QApplication,
) -> None:
    restricted = _session(must_change=True)
    authentication = FakeAuthentication(restricted)
    authentication.change_result = _session()
    resources = FakeResources(authentication, FakeUsers(), _logger())
    controller = DesktopApplication(qapp, cast("object", resources))
    controller.start()
    controller.login_window.username_input.setText("admin")
    controller.login_window.secret_input.setText("temporary-secret")
    qtbot.mouseClick(controller.login_window.login_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: controller.password_dialog is not None, timeout=3_000)
    dialog = cast(PasswordChangeDialog, controller.password_dialog)
    dialog.current_input.setText("temporary-secret")
    dialog.new_input.setText("replacement-secret")
    dialog.confirm_input.setText("replacement-secret")
    qtbot.mouseClick(dialog.change_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: controller.main_window is not None and controller.main_window.isVisible(),
        timeout=3_000,
    )
    assert controller.session is not None and not controller.session.must_change_password
    assert authentication.change_calls[0][1:] == (
        "temporary-secret",
        "replacement-secret",
    )
    controller.shutdown()


@pytest.mark.parametrize(
    ("role", "has_users"),
    [
        (UserRole.ADMIN, True),
        (UserRole.WAREHOUSE_OPERATOR, False),
        (UserRole.SUPERVISOR, False),
    ],
)
def test_role_based_navigation(
    role: UserRole,
    has_users: bool,
    thread_pool: QThreadPool,
) -> None:
    window = MainWindow(
        _session(role),
        cast("object", FakeUsers()),
        thread_pool,
        _logger(),
    )
    assert window.has_route("users") is has_users
    if role is UserRole.WAREHOUSE_OPERATOR:
        assert window.has_route("shipments")
        assert not window.has_route("reports")
    if role is UserRole.SUPERVISOR:
        assert window.has_route("dashboard")
        assert window.has_route("reports")
        assert window.has_route("audit")
    window.hide()
    window.deleteLater()


def test_create_user_and_reset_password_show_each_temporary_secret_once(
    qtbot: QtBot,
    thread_pool: QThreadPool,
) -> None:
    users = FakeUsers()
    page = UsersPage(_session(), cast("object", users), thread_pool, _logger())
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(
        lambda: page.table.rowCount() == 2 and page.create_button.isEnabled(),
        timeout=3_000,
    )

    qtbot.mouseClick(page.create_button, Qt.MouseButton.LeftButton)
    dialog = cast(CreateUserDialog, page._create_dialog)
    dialog.username_input.setText("new.operator")
    dialog.role_input.setCurrentIndex(1)
    qtbot.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(users.created), timeout=3_000)
    qtbot.waitUntil(
        lambda: page._credential_dialog is not None and page._credential_dialog.isVisible(),
        timeout=3_000,
    )
    created_dialog = cast(TemporaryCredentialDialog, page._credential_dialog)
    assert created_dialog.credential_value.text() == "created-user-secret"
    assert users.created == [("new.operator", UserRole.WAREHOUSE_OPERATOR)]
    created_dialog.accept()
    assert created_dialog.credential_value.text() == ""

    qtbot.waitUntil(lambda: page.table.rowCount() == 3, timeout=3_000)
    operator_row = next(
        row for row in range(page.table.rowCount()) if page.table.item(row, 0).text() == "operator"
    )
    page.table.selectRow(operator_row)
    qtbot.mouseClick(page.reset_button, Qt.MouseButton.LeftButton)
    confirmation = cast(ConfirmDialog, page._confirm_dialog)
    confirm_button = confirmation.findChild(QPushButton, "confirmAction")
    assert confirm_button is not None
    qtbot.mouseClick(confirm_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: (
            isinstance(page._credential_dialog, ResetPasswordDialog)
            and page._credential_dialog.isVisible()
        ),
        timeout=3_000,
    )
    reset_dialog = cast(ResetPasswordDialog, page._credential_dialog)
    assert reset_dialog.credential_value.text() == "reset-user-secret"
    assert users.reset == [2]
    reset_dialog.accept()


def test_logout_returns_to_login_without_restart(qtbot: QtBot, qapp: QApplication) -> None:
    authentication = FakeAuthentication(_session())
    resources = FakeResources(authentication, FakeUsers(), _logger())
    controller = DesktopApplication(qapp, cast("object", resources))
    controller.start()
    controller.login_window.username_input.setText("admin")
    controller.login_window.secret_input.setText("valid-password")
    qtbot.mouseClick(controller.login_window.login_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: controller.main_window is not None, timeout=3_000)
    main = cast(MainWindow, controller.main_window)
    logout = main.sidebar.findChild(QPushButton, "nav_logout")
    assert logout is not None
    qtbot.mouseClick(logout, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: controller.main_window is None and controller.login_window.isVisible(),
        timeout=3_000,
    )
    assert len(authentication.logout_calls) == 1
    assert controller.session is None
    controller.shutdown()


def test_unexpected_login_error_never_exposes_traceback(
    qtbot: QtBot,
    thread_pool: QThreadPool,
) -> None:
    logger = logging.getLogger("warehouse_control_center.ui.unexpected-test")
    log_output = StringIO()
    logger.handlers.clear()
    logger.addHandler(logging.StreamHandler(log_output))
    logger.propagate = False
    authentication = FakeAuthentication(RuntimeError("technical traceback detail"))
    window = LoginWindow(cast("object", authentication), thread_pool, logger)
    qtbot.addWidget(window)
    window.show()
    entered_secret = "never-log-this-password"
    window.secret_input.setText(entered_secret)
    qtbot.mouseClick(window.login_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.status.isVisible(), timeout=3_000)
    assert window.status.message == "An unexpected error occurred."
    assert "technical traceback detail" not in window.status.message
    assert "technical traceback detail" in log_output.getvalue()
    assert entered_secret not in log_output.getvalue()


def test_secret_values_are_not_used_as_object_names_or_settings_keys(
    qtbot: QtBot,
    thread_pool: QThreadPool,
) -> None:
    login = LoginWindow(cast("object", FakeAuthentication(_session())), thread_pool, _logger())
    change = PasswordChangeDialog(
        _session(must_change=True),
        cast("object", FakeAuthentication(_session())),
        thread_pool,
        _logger(),
    )
    qtbot.addWidget(login)
    qtbot.addWidget(change)
    object_names = {
        child.objectName().casefold()
        for widget in (login, change)
        for child in widget.findChildren(QObject)
        if child.objectName()
    }
    assert all("password" not in name for name in object_names)
    assert "password" not in {field.name for field in fields(SessionContext)}
    assert "password" not in {field.name for field in fields(UserDTO)}
    one_time_secret = "dto-one-time-secret"
    credential = _credential(_user(9, "dto-user", UserRole.ADMIN), one_time_secret)
    assert one_time_secret not in repr(credential)
    presentation_root = (
        Path(__file__).parents[2] / "src" / "warehouse_control_center" / "presentation"
    )
    source = "".join(path.read_text(encoding="utf-8") for path in presentation_root.rglob("*.py"))
    assert "QSettings" not in source
