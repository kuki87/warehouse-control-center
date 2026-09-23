"""Desktop lifecycle orchestration over the audited Phase 2 services."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import cast

from PySide6.QtCore import QObject, QThreadPool
from PySide6.QtWidgets import QApplication, QMessageBox

from warehouse_control_center.application.dto import SessionContext
from warehouse_control_center.bootstrap import ApplicationResources
from warehouse_control_center.domain.exceptions import DatabaseSchemaError
from warehouse_control_center.presentation.qt.dialogs.password_change_dialog import (
    PasswordChangeDialog,
)
from warehouse_control_center.presentation.qt.dialogs.temporary_credential_dialog import (
    FirstRunDialog,
)
from warehouse_control_center.presentation.qt.error_mapping import (
    log_unexpected,
    translate_error,
)
from warehouse_control_center.presentation.qt.style import APPLICATION_STYLESHEET
from warehouse_control_center.presentation.qt.windows import LoginWindow, MainWindow
from warehouse_control_center.presentation.qt.workers import DatabaseTaskRunner


class DesktopApplication(QObject):
    """Own window transitions and the sole in-memory reference to the active session."""

    def __init__(
        self,
        application: QApplication,
        resources: ApplicationResources,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(application)
        self._application = application
        self._resources = resources
        self._logger = resources.logger
        self._thread_pool = thread_pool or QThreadPool(self)
        self._thread_pool.setMaxThreadCount(4)
        self._tasks = DatabaseTaskRunner(self._thread_pool, self)
        self._session: SessionContext | None = None
        self._shutdown_complete = False
        self._exit_after_logout = False
        self._logout_pending = False
        self.login_window = LoginWindow(
            resources.authentication,
            self._thread_pool,
            self._logger,
        )
        self.login_window.authenticated.connect(self._authenticated)
        self.login_window.exit_requested.connect(self._application.quit)
        self.main_window: MainWindow | None = None
        self.password_dialog: PasswordChangeDialog | None = None
        self.first_run_dialog: FirstRunDialog | None = None
        self._application.aboutToQuit.connect(self.shutdown)

    @property
    def session(self) -> SessionContext | None:
        return self._session

    def start(self) -> None:
        initial = self._resources.initial_administrator
        if initial is not None:
            dialog = FirstRunDialog(initial)
            self.first_run_dialog = dialog
            dialog.finished.connect(lambda result: self.login_window.reset_for_sign_in())
            dialog.open()
            return
        self.login_window.reset_for_sign_in()

    def _authenticated(self, result: object) -> None:
        session = cast(SessionContext, result)
        if session.must_change_password:
            self._show_password_change(session)
            return
        self._open_main(session)

    def _show_password_change(self, session: SessionContext) -> None:
        dialog = PasswordChangeDialog(
            session,
            self._resources.authentication,
            self._thread_pool,
            self._logger,
        )
        self.password_dialog = dialog
        dialog.session_changed.connect(self._password_changed)
        dialog.rejected.connect(self._password_change_cancelled)
        dialog.open()
        self.login_window.hide()

    def _password_changed(self, result: object) -> None:
        self._open_main(cast(SessionContext, result))

    def _password_change_cancelled(self) -> None:
        if self.main_window is None:
            self._session = None
            self.login_window.reset_for_sign_in()

    def _open_main(self, session: SessionContext) -> None:
        self._session = session
        window = MainWindow(
            session,
            self._resources.users,
            self._thread_pool,
            self._logger,
            shipments=self._resources.shipments,
            timezone_name=self._resources.settings.timezone,
        )
        self.main_window = window
        window.logout_requested.connect(lambda: self._begin_logout(exit_after=False))
        window.application_close_requested.connect(lambda: self._begin_logout(exit_after=True))
        window.session_invalidated.connect(self._session_invalidated)
        window.show()
        self.login_window.hide()

    def _begin_logout(self, *, exit_after: bool) -> None:
        if self._logout_pending:
            return
        session = self._session
        if session is None:
            if exit_after:
                self._application.quit()
            else:
                self.login_window.reset_for_sign_in()
            return
        self._exit_after_logout = exit_after
        self._logout_pending = True
        self._tasks.submit(
            lambda: self._resources.authentication.logout(session),
            on_result=self._logged_out,
            on_error=self._logout_failed,
        )

    def _logged_out(self, result: object) -> None:
        del result
        self._logout_pending = False
        self._session = None
        if self.main_window is not None:
            self.main_window.hide()
            self.main_window.deleteLater()
            self.main_window = None
        if self._exit_after_logout:
            self._application.quit()
        else:
            self.login_window.reset_for_sign_in()

    def _logout_failed(self, error: BaseException) -> None:
        self._logout_pending = False
        presentation = translate_error(error)
        if presentation.unexpected:
            log_unexpected(self._logger, error, "logout")
        QMessageBox.warning(
            self.main_window,
            "Unable to log out",
            presentation.message,
        )

    def _session_invalidated(self) -> None:
        self._session = None
        if self.main_window is not None:
            self.main_window.hide()
            self.main_window.deleteLater()
            self.main_window = None
        self.login_window.reset_for_sign_in()
        self.login_window.status.show_message(
            "Your session is no longer valid. Please sign in again."
        )

    def shutdown(self) -> None:
        if self._shutdown_complete:
            return
        self._shutdown_complete = True
        self._thread_pool.clear()
        self._thread_pool.waitForDone()
        self._resources.shutdown()


def run_qt_application(
    resources: ApplicationResources,
    argv: Sequence[str] | None = None,
) -> int:
    """Create the QApplication, start the desktop flow, and own its event loop."""
    existing = QApplication.instance()
    if existing is None:
        application = QApplication(list(argv) if argv is not None else sys.argv)
    elif isinstance(existing, QApplication):
        application = existing
    else:
        raise RuntimeError("A non-GUI Qt application already exists")
    application.setApplicationName("Warehouse Control Center")
    application.setOrganizationName("Warehouse Control Center")
    application.setQuitOnLastWindowClosed(False)
    application.setStyleSheet(APPLICATION_STYLESHEET)
    controller = DesktopApplication(application, resources)
    controller.start()
    return application.exec()


def show_startup_error(error: BaseException, argv: Sequence[str] | None = None) -> None:
    """Show a safe startup failure even when bootstrap failed before QApplication creation."""
    existing = QApplication.instance()
    application = (
        existing
        if isinstance(existing, QApplication)
        else QApplication(list(argv) if argv is not None else sys.argv)
    )
    del application
    message = (
        str(error)
        if isinstance(error, DatabaseSchemaError)
        else "Warehouse Control Center could not start. See app.log for technical details."
    )
    QMessageBox.critical(None, "Warehouse Control Center", message)
