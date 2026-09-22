"""Mandatory password-change flow backed by the audited authentication service."""

import logging
from typing import cast

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from warehouse_control_center.application.dto import SessionContext
from warehouse_control_center.application.services import AuthenticationService
from warehouse_control_center.domain.validation import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from warehouse_control_center.presentation.qt.error_mapping import (
    log_unexpected,
    translate_error,
)
from warehouse_control_center.presentation.qt.widgets.status_banner import StatusBanner
from warehouse_control_center.presentation.qt.workers import DatabaseTaskRunner


class PasswordChangeDialog(QDialog):
    session_changed = Signal(object)

    def __init__(
        self,
        session: SessionContext,
        authentication: AuthenticationService,
        thread_pool: QThreadPool,
        logger: logging.Logger,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._authentication = authentication
        self._logger = logger
        self._tasks = DatabaseTaskRunner(thread_pool, self)
        self.setWindowTitle("Password change required")
        self.setModal(True)
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(15)
        heading = QLabel("Change your temporary password")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        policy = QLabel(
            f"Choose {PASSWORD_MIN_LENGTH}–{PASSWORD_MAX_LENGTH} characters. "
            "The new password must differ from the current password."
        )
        policy.setWordWrap(True)
        policy.setObjectName("mutedText")
        layout.addWidget(policy)

        form = QFormLayout()
        form.setSpacing(12)
        self.current_input = self._secret_field("currentSecret")
        self.new_input = self._secret_field("newSecret")
        self.confirm_input = self._secret_field("confirmSecret")
        form.addRow("Current password", self.current_input)
        form.addRow("New password", self.new_input)
        form.addRow("Confirm new password", self.confirm_input)
        layout.addLayout(form)
        self.status = StatusBanner()
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        cancel = QPushButton("Back to sign in")
        cancel.setProperty("secondary", True)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        actions.addStretch(1)
        self.change_button = QPushButton("Change password")
        self.change_button.setObjectName("changeSecretAction")
        self.change_button.clicked.connect(self._submit)
        actions.addWidget(self.change_button)
        layout.addLayout(actions)
        self.confirm_input.returnPressed.connect(self._submit)

    @staticmethod
    def _secret_field(name: str) -> QLineEdit:
        field = QLineEdit()
        field.setObjectName(name)
        field.setEchoMode(QLineEdit.EchoMode.Password)
        return field

    def _submit(self) -> None:
        current = self.current_input.text()
        new = self.new_input.text()
        confirmation = self.confirm_input.text()
        if new != confirmation:
            self.status.show_message("The new passwords do not match.")
            return
        self.status.clear()
        self._set_busy(True)
        self.current_input.clear()
        self.new_input.clear()
        self.confirm_input.clear()
        self._tasks.submit(
            lambda: self._authentication.change_password(self._session, current, new),
            on_result=self._changed,
            on_error=self._failed,
            on_finished=lambda: self._set_busy(False),
        )

    def _changed(self, result: object) -> None:
        session = cast(SessionContext, result)
        self.session_changed.emit(session)
        self.accept()

    def _failed(self, error: BaseException) -> None:
        presentation = translate_error(error)
        if presentation.unexpected:
            log_unexpected(self._logger, error, "password change")
        self.status.show_message(presentation.message)

    def _set_busy(self, busy: bool) -> None:
        for field in (self.current_input, self.new_input, self.confirm_input):
            field.setEnabled(not busy)
        self.change_button.setEnabled(not busy)
        self.change_button.setText("Changing…" if busy else "Change password")
