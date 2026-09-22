"""Real user-administration UI backed exclusively by the audited UserService."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from warehouse_control_center.application.dto import SessionContext, TemporaryCredential, UserDTO
from warehouse_control_center.application.services import UserService
from warehouse_control_center.domain.enums import UserRole
from warehouse_control_center.presentation.qt.dialogs.confirm_dialog import ConfirmDialog
from warehouse_control_center.presentation.qt.dialogs.create_user_dialog import CreateUserDialog
from warehouse_control_center.presentation.qt.dialogs.reset_password_dialog import (
    ResetPasswordDialog,
)
from warehouse_control_center.presentation.qt.dialogs.temporary_credential_dialog import (
    TemporaryCredentialDialog,
)
from warehouse_control_center.presentation.qt.error_mapping import (
    log_unexpected,
    translate_error,
)
from warehouse_control_center.presentation.qt.widgets.status_banner import StatusBanner
from warehouse_control_center.presentation.qt.workers import DatabaseTaskRunner


class RoleDialog(QDialog):
    def __init__(self, current: UserRole, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change role")
        self.setModal(True)
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.addWidget(QLabel("Select the user's new role."))
        self.role_input = QComboBox()
        for role in UserRole:
            self.role_input.addItem(role.value.replace("_", " ").title(), role.value)
            if role is current:
                self.role_input.setCurrentIndex(self.role_input.count() - 1)
        layout.addWidget(self.role_input)
        actions = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setProperty("secondary", True)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        actions.addStretch(1)
        apply_button = QPushButton("Change role")
        apply_button.setObjectName("applyRoleAction")
        apply_button.clicked.connect(self.accept)
        actions.addWidget(apply_button)
        layout.addLayout(actions)

    def selected_role(self) -> UserRole | None:
        try:
            return UserRole(self.role_input.currentData())
        except (TypeError, ValueError):
            return None


class UsersPage(QWidget):
    session_invalidated = Signal()

    _HEADERS = (
        "Username",
        "Role",
        "Active",
        "Must Change Password",
        "Archived",
        "Created",
        "Updated",
    )

    def __init__(
        self,
        session: SessionContext,
        users: UserService,
        thread_pool: QThreadPool,
        logger: logging.Logger,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("users_page")
        self._session = session
        self._users = users
        self._logger = logger
        self._tasks = DatabaseTaskRunner(thread_pool, self)
        self._records: dict[int, UserDTO] = {}
        self._create_dialog: CreateUserDialog | None = None
        self._credential_dialog: TemporaryCredentialDialog | None = None
        self._confirm_dialog: ConfirmDialog | None = None
        self._role_dialog: RoleDialog | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        title_row = QHBoxLayout()
        title = QLabel("User Administration")
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.refresh_button = self._button("Refresh", "refreshUsers", self.refresh, secondary=True)
        title_row.addWidget(self.refresh_button)
        self.create_button = self._button("Create User", "openCreateUser", self.open_create)
        title_row.addWidget(self.create_button)
        layout.addLayout(title_row)

        self.status = StatusBanner()
        layout.addWidget(self.status)
        self.table = QTableWidget(0, len(self._HEADERS))
        self.table.setObjectName("usersTable")
        self.table.setHorizontalHeaderLabels(self._HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._update_action_state)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.role_button = self._button("Change Role", "changeRole", self.open_role)
        self.activate_button = self._button("Activate", "activateUser", self.activate)
        self.deactivate_button = self._button(
            "Deactivate", "deactivateUser", self.deactivate, secondary=True
        )
        self.archive_button = self._button("Archive", "archiveUser", self.archive, secondary=True)
        self.restore_button = self._button("Restore", "restoreUser", self.restore)
        self.reset_button = self._button("Reset Password", "resetUserSecret", self.reset_password)
        for button in (
            self.role_button,
            self.activate_button,
            self.deactivate_button,
            self.archive_button,
            self.restore_button,
            self.reset_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self._update_action_state()
        QTimer.singleShot(0, self.refresh)

    @staticmethod
    def _button(
        label: str,
        name: str,
        callback: Callable[[], None],
        *,
        secondary: bool = False,
    ) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName(name)
        button.setProperty("secondary", secondary)
        button.clicked.connect(callback)
        return button

    def refresh(self) -> None:
        self._set_page_busy(True)
        self.status.clear()
        self._tasks.submit(
            lambda: self._users.list_users(self._session, include_archived=True),
            on_result=self._populate,
            on_error=lambda error: self._handle_error(error, "refresh users"),
            on_finished=lambda: self._set_page_busy(False),
        )

    def _populate(self, result: object) -> None:
        records = cast(list[UserDTO], result)
        self._records = {record.id: record for record in records}
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = (
                record.username,
                record.role.value.replace("_", " ").title(),
                "Yes" if record.active else "No",
                "Yes" if record.must_change_password else "No",
                "Yes" if record.archived_at is not None else "No",
                self._timestamp(record.created_at),
                self._timestamp(record.updated_at),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, record.id)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        self._update_action_state()

    @staticmethod
    def _timestamp(value: object) -> str:
        if isinstance(value, datetime):
            return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
        return ""

    def selected_user(self) -> UserDTO | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        user_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return self._records.get(user_id) if isinstance(user_id, int) else None

    def open_create(self) -> None:
        dialog = CreateUserDialog(self)
        self._create_dialog = dialog
        dialog.create_requested.connect(self._create_requested)
        dialog.open()

    def _create_requested(self, username: str, role: object) -> None:
        dialog = self._create_dialog
        if dialog is None or not isinstance(role, UserRole):
            return
        dialog.set_busy(True)
        self._tasks.submit(
            lambda: self._users.create_user(self._session, username, role),
            on_result=self._user_created,
            on_error=lambda error: self._dialog_error(dialog, error, "create user"),
        )

    def _user_created(self, result: object) -> None:
        if self._create_dialog is not None:
            self._create_dialog.accept()
        credential = cast(TemporaryCredential, result)
        self._credential_dialog = TemporaryCredentialDialog(
            credential,
            title="User created",
            explanation=(
                "This temporary password is shown once. Give it to the user through an "
                "appropriate channel; they must change it at sign-in."
            ),
            parent=self,
        )
        self._credential_dialog.open()
        self.refresh()

    def open_role(self) -> None:
        record = self.selected_user()
        if record is None:
            return
        dialog = RoleDialog(record.role, self)
        self._role_dialog = dialog
        dialog.accepted.connect(lambda: self._apply_role(dialog, record.id))
        dialog.open()

    def _apply_role(self, dialog: RoleDialog, user_id: int) -> None:
        role = dialog.selected_role()
        if role is not None:
            self._mutate(lambda: self._users.change_role(self._session, user_id, role), "role")

    def activate(self) -> None:
        record = self.selected_user()
        if record is not None:
            self._mutate(lambda: self._users.activate_user(self._session, record.id), "activation")

    def deactivate(self) -> None:
        self._confirm_mutation(
            "Deactivate user",
            "The selected user will no longer be able to sign in.",
            lambda user_id: self._users.deactivate_user(self._session, user_id),
            "deactivation",
            destructive=True,
        )

    def archive(self) -> None:
        self._confirm_mutation(
            "Archive user",
            "The selected user will be archived and unable to sign in.",
            lambda user_id: self._users.archive_user(self._session, user_id),
            "archive",
            destructive=True,
        )

    def restore(self) -> None:
        record = self.selected_user()
        if record is not None:
            self._mutate(lambda: self._users.restore_user(self._session, record.id), "restore")

    def reset_password(self) -> None:
        record = self.selected_user()
        if record is None:
            return
        dialog = ConfirmDialog(
            "Reset password",
            f"Generate a new one-time password for {record.username}?",
            destructive=True,
            parent=self,
        )
        self._confirm_dialog = dialog
        dialog.accepted.connect(lambda: self._reset_confirmed(record.id))
        dialog.open()

    def _reset_confirmed(self, user_id: int) -> None:
        self._set_page_busy(True)
        self._tasks.submit(
            lambda: self._users.reset_password(self._session, user_id),
            on_result=self._password_reset,
            on_error=lambda error: self._handle_error(error, "reset password"),
            on_finished=lambda: self._set_page_busy(False),
        )

    def _password_reset(self, result: object) -> None:
        self._credential_dialog = ResetPasswordDialog(cast(TemporaryCredential, result), self)
        self._credential_dialog.open()
        self.refresh()

    def _confirm_mutation(
        self,
        title: str,
        message: str,
        operation: Callable[[int], object],
        context: str,
        *,
        destructive: bool,
    ) -> None:
        record = self.selected_user()
        if record is None:
            return
        dialog = ConfirmDialog(title, message, destructive=destructive, parent=self)
        self._confirm_dialog = dialog
        dialog.accepted.connect(lambda: self._mutate(lambda: operation(record.id), context))
        dialog.open()

    def _mutate(self, operation: Callable[[], object], context: str) -> None:
        self._set_page_busy(True)
        self.status.clear()
        self._tasks.submit(
            operation,
            on_result=lambda result: self._mutation_complete(result),
            on_error=lambda error: self._handle_error(error, context),
            on_finished=lambda: self._set_page_busy(False),
        )

    def _mutation_complete(self, result: object) -> None:
        del result
        self.status.show_message("User updated successfully.", status="success")
        self.refresh()

    def _dialog_error(
        self,
        dialog: CreateUserDialog,
        error: BaseException,
        context: str,
    ) -> None:
        presentation = translate_error(error)
        if presentation.session_invalid:
            dialog.reject()
            self.session_invalidated.emit()
            return
        if presentation.unexpected:
            log_unexpected(self._logger, error, context)
        dialog.show_error(presentation.message)

    def _handle_error(self, error: BaseException, context: str) -> None:
        presentation = translate_error(error)
        if presentation.session_invalid:
            self.session_invalidated.emit()
            return
        if presentation.unexpected:
            log_unexpected(self._logger, error, context)
        self.status.show_message(presentation.message)

    def _set_page_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)
        self.create_button.setEnabled(not busy)
        if busy:
            for button in self._action_buttons():
                button.setEnabled(False)
        else:
            self._update_action_state()

    def _action_buttons(self) -> tuple[QPushButton, ...]:
        return (
            self.role_button,
            self.activate_button,
            self.deactivate_button,
            self.archive_button,
            self.restore_button,
            self.reset_button,
        )

    def _update_action_state(self) -> None:
        record = self.selected_user()
        for button in self._action_buttons():
            button.setEnabled(record is not None)
        if record is None:
            return
        archived = record.archived_at is not None
        self.activate_button.setEnabled(not record.active and not archived)
        self.deactivate_button.setEnabled(record.active and not archived)
        self.archive_button.setEnabled(not archived)
        self.restore_button.setEnabled(archived)
        self.reset_button.setEnabled(not archived and record.id != self._session.user_id)
