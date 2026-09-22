"""Consistent confirmation dialog for administrative state changes."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ConfirmDialog(QDialog):
    def __init__(
        self,
        title: str,
        message: str,
        *,
        destructive: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(18)
        text = QLabel(message)
        text.setWordWrap(True)
        layout.addWidget(text)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        confirm = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if confirm is not None:
            confirm.setText("Confirm")
            confirm.setObjectName("confirmAction")
            if destructive:
                confirm.setProperty("danger", True)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if isinstance(cancel, QPushButton):
            cancel.setProperty("secondary", True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
