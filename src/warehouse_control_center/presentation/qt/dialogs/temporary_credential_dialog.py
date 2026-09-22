"""One-display credential dialogs for bootstrap, user creation, and reset."""

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from warehouse_control_center.application.dto import TemporaryCredential


class TemporaryCredentialDialog(QDialog):
    def __init__(
        self,
        credential: TemporaryCredential,
        *,
        title: str,
        explanation: str,
        continue_label: str = "Done",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(540)
        temporary_secret = credential.take_temporary_password()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(16)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        description = QLabel(explanation)
        description.setWordWrap(True)
        description.setObjectName("mutedText")
        layout.addWidget(description)

        self.credential_value = QLineEdit(temporary_secret)
        self.credential_value.setObjectName("credentialValue")
        self.credential_value.setReadOnly(True)
        self.credential_value.setEchoMode(QLineEdit.EchoMode.Normal)
        layout.addWidget(self.credential_value)

        actions = QHBoxLayout()
        self.copy_button = QPushButton("Copy password")
        self.copy_button.setObjectName("copyCredential")
        self.copy_button.setProperty("secondary", True)
        self.copy_button.clicked.connect(self._copy)
        actions.addWidget(self.copy_button)
        actions.addStretch(1)
        continue_button = QPushButton(continue_label)
        continue_button.setObjectName("continueAction")
        continue_button.clicked.connect(self.accept)
        actions.addWidget(continue_button)
        layout.addLayout(actions)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.credential_value.text())
        self.copy_button.setText("Copied")

    def done(self, result: int) -> None:
        self.credential_value.clear()
        super().done(result)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.credential_value.clear()
        super().closeEvent(event)


class FirstRunDialog(TemporaryCredentialDialog):
    def __init__(self, credential: TemporaryCredential, parent: QWidget | None = None) -> None:
        super().__init__(
            credential,
            title="First-run administrator",
            explanation=(
                "This temporary administrator password is shown once. "
                "You must change it before using the application."
            ),
            continue_label="Continue to sign in",
            parent=parent,
        )
