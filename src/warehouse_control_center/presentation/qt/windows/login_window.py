"""Keyboard-friendly authentication window with asynchronous service execution."""

import logging
from typing import cast

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from warehouse_control_center.application.dto import SessionContext
from warehouse_control_center.application.services import AuthenticationService
from warehouse_control_center.presentation.qt.error_mapping import (
    log_unexpected,
    translate_error,
)
from warehouse_control_center.presentation.qt.widgets.status_banner import StatusBanner
from warehouse_control_center.presentation.qt.workers import DatabaseTaskRunner


class LoginWindow(QWidget):
    authenticated = Signal(object)
    exit_requested = Signal()

    def __init__(
        self,
        authentication: AuthenticationService,
        thread_pool: QThreadPool,
        logger: logging.Logger,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._authentication = authentication
        self._logger = logger
        self._tasks = DatabaseTaskRunner(thread_pool, self)
        self.setObjectName("loginRoot")
        self.setWindowTitle("Warehouse Control Center — Sign in")
        self.setFixedSize(520, 570)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 42, 48, 42)
        outer.addStretch(1)
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(36, 34, 36, 34)
        card_layout.setSpacing(14)
        brand = QLabel("WAREHOUSE CONTROL CENTER")
        brand.setStyleSheet("color: #2563eb; font-size: 13px; font-weight: 700;")
        card_layout.addWidget(brand)
        title = QLabel("Sign in")
        title.setObjectName("pageTitle")
        card_layout.addWidget(title)
        subtitle = QLabel("Use your warehouse account to continue.")
        subtitle.setObjectName("mutedText")
        card_layout.addWidget(subtitle)
        card_layout.addSpacing(8)

        username_label = QLabel("Username")
        username_label.setObjectName("fieldLabel")
        card_layout.addWidget(username_label)
        self.username_input = QLineEdit()
        self.username_input.setObjectName("usernameInput")
        card_layout.addWidget(self.username_input)

        secret_label = QLabel("Password")
        secret_label.setObjectName("fieldLabel")
        card_layout.addWidget(secret_label)
        self.secret_input = QLineEdit()
        self.secret_input.setObjectName("secretInput")
        self.secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        card_layout.addWidget(self.secret_input)
        self.status = StatusBanner()
        card_layout.addWidget(self.status)

        actions = QHBoxLayout()
        self.exit_button = QPushButton("Exit")
        self.exit_button.setObjectName("exitAction")
        self.exit_button.setProperty("secondary", True)
        self.exit_button.clicked.connect(self.exit_requested)
        actions.addWidget(self.exit_button)
        actions.addStretch(1)
        self.login_button = QPushButton("Sign in")
        self.login_button.setObjectName("loginAction")
        self.login_button.clicked.connect(self.submit)
        actions.addWidget(self.login_button)
        card_layout.addLayout(actions)
        outer.addWidget(card)
        outer.addStretch(1)

        self.username_input.returnPressed.connect(self.submit)
        self.secret_input.returnPressed.connect(self.submit)
        self.setTabOrder(self.username_input, self.secret_input)
        self.setTabOrder(self.secret_input, self.login_button)
        self.setTabOrder(self.login_button, self.exit_button)

    def submit(self) -> None:
        username = self.username_input.text()
        secret = self.secret_input.text()
        self.secret_input.clear()
        self.status.clear()
        self._set_busy(True)
        self._tasks.submit(
            lambda: self._authentication.login(username, secret),
            on_result=self._authenticated,
            on_error=self._failed,
            on_finished=lambda: self._set_busy(False),
        )

    def _authenticated(self, result: object) -> None:
        self.authenticated.emit(cast(SessionContext, result))

    def _failed(self, error: BaseException) -> None:
        presentation = translate_error(error)
        if presentation.unexpected:
            log_unexpected(self._logger, error, "login")
        self.status.show_message(presentation.message)
        self.secret_input.setFocus()

    def _set_busy(self, busy: bool) -> None:
        self.username_input.setEnabled(not busy)
        self.secret_input.setEnabled(not busy)
        self.login_button.setEnabled(not busy)
        self.exit_button.setEnabled(not busy)
        self.login_button.setText("Signing in…" if busy else "Sign in")

    def reset_for_sign_in(self) -> None:
        self.secret_input.clear()
        self.status.clear()
        self._set_busy(False)
        self.show()
        self.raise_()
        self.activateWindow()
        self.username_input.setFocus()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())
        self.username_input.setFocus()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.exit_requested.emit()
        event.accept()
