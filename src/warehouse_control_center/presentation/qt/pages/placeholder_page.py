"""Honest placeholders for business functionality scheduled for later phases."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderPage(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(f"{title.casefold().replace(' ', '_')}_page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 32, 36, 32)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        message = QLabel("Coming in a later phase")
        message.setObjectName("mutedText")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet("font-size: 18px; padding: 80px;")
        layout.addWidget(message, 1)
