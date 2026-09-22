"""Collect validated user-creation intent; the UserService remains authoritative."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from warehouse_control_center.domain.enums import UserRole
from warehouse_control_center.presentation.qt.widgets.status_banner import StatusBanner


class CreateUserDialog(QDialog):
    create_requested = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create user")
        self.setModal(True)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(16)
        heading = QLabel("Create user")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        form = QFormLayout()
        form.setSpacing(12)
        self.username_input = QLineEdit()
        self.username_input.setObjectName("newUsername")
        self.username_input.setPlaceholderText("e.g. warehouse.operator")
        self.role_input = QComboBox()
        self.role_input.setObjectName("newUserRole")
        for role in UserRole:
            self.role_input.addItem(role.value.replace("_", " ").title(), role.value)
        form.addRow("Username", self.username_input)
        form.addRow("Role", self.role_input)
        layout.addLayout(form)
        self.status = StatusBanner()
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setProperty("secondary", True)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self.create_button = QPushButton("Create user")
        self.create_button.setObjectName("createUserAction")
        self.create_button.clicked.connect(self._submit)
        actions.addWidget(self.create_button)
        layout.addLayout(actions)

    def _submit(self) -> None:
        try:
            role = UserRole(self.role_input.currentData())
        except (TypeError, ValueError):
            self.status.show_message("Choose a valid role.")
            return
        self.status.clear()
        self.create_requested.emit(self.username_input.text(), role)

    def set_busy(self, busy: bool) -> None:
        self.username_input.setEnabled(not busy)
        self.role_input.setEnabled(not busy)
        self.create_button.setEnabled(not busy)
        self.create_button.setText("Creating…" if busy else "Create user")

    def show_error(self, message: str) -> None:
        self.status.show_message(message)
        self.set_busy(False)
