"""Inline status and error feedback that does not interrupt keyboard workflows."""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


class StatusBanner(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusBanner")
        self._label = QLabel()
        self._label.setWordWrap(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.addWidget(self._label)
        self.hide()

    def show_message(self, message: str, *, status: str = "error") -> None:
        self._label.setText(message)
        self.setProperty("status", status)
        self.style().unpolish(self)
        self.style().polish(self)
        self.show()

    def clear(self) -> None:
        self._label.clear()
        self.hide()

    @property
    def message(self) -> str:
        return self._label.text()
