"""Contract-client forms and read-only details."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from warehouse_control_center.application.dto import ClientDTO
from warehouse_control_center.presentation.qt.shipment_formatting import display_timestamp
from warehouse_control_center.presentation.qt.widgets.status_banner import StatusBanner


def _line(name: str) -> QLineEdit:
    field = QLineEdit()
    field.setObjectName(name)
    return field


class ClientDialog(QDialog):
    save_requested = Signal(object)

    def __init__(self, client: ClientDTO | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self.setWindowTitle("Edit client" if client else "New client")
        self.setModal(True)
        self.resize(620, 680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        title = QLabel("Edit contract client" if client else "New contract client")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.setSpacing(10)
        self.code_input = _line("clientCode")
        self.company_input = _line("clientCompany")
        self.tax_id_input = _line("clientTaxId")
        self.address_input = _line("clientAddress")
        self.city_input = _line("clientCity")
        self.contact_input = _line("clientContact")
        self.phone_input = _line("clientPhone")
        self.email_input = _line("clientEmail")
        self.contract_number_input = _line("clientContractNumber")
        self.contract_start_input = _line("clientContractStart")
        self.contract_end_input = _line("clientContractEnd")
        self.contract_start_input.setPlaceholderText("YYYY-MM-DD")
        self.contract_end_input.setPlaceholderText("YYYY-MM-DD")
        self.notes_input = QPlainTextEdit()
        self.notes_input.setObjectName("clientNotes")
        self.notes_input.setMaximumHeight(90)
        for label, field in (
            ("Client code *", self.code_input),
            ("Company name *", self.company_input),
            ("Tax ID", self.tax_id_input),
            ("Address *", self.address_input),
            ("City *", self.city_input),
            ("Contact name", self.contact_input),
            ("Phone", self.phone_input),
            ("Email", self.email_input),
            ("Contract number", self.contract_number_input),
            ("Contract start", self.contract_start_input),
            ("Contract end", self.contract_end_input),
            ("Notes", self.notes_input),
        ):
            form.addRow(label, field)
        layout.addLayout(form)
        if client is not None:
            self._populate(client)
        self.status = StatusBanner()
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setProperty("secondary", True)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self.save_button = QPushButton("Save client")
        self.save_button.setObjectName("saveClientAction")
        self.save_button.clicked.connect(self._submit)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)

    def _populate(self, client: ClientDTO) -> None:
        self.code_input.setText(client.client_code)
        self.company_input.setText(client.company_name)
        self.tax_id_input.setText(client.tax_id or "")
        self.address_input.setText(client.address)
        self.city_input.setText(client.city)
        self.contact_input.setText(client.contact_name or "")
        self.phone_input.setText(client.phone or "")
        self.email_input.setText(client.email or "")
        self.contract_number_input.setText(client.contract_number or "")
        self.contract_start_input.setText(
            client.contract_start.isoformat() if client.contract_start else ""
        )
        self.contract_end_input.setText(
            client.contract_end.isoformat() if client.contract_end else ""
        )
        self.notes_input.setPlainText(client.notes or "")

    @staticmethod
    def _optional_text(field: QLineEdit) -> str | None:
        return field.text() if field.text().strip() else None

    @staticmethod
    def _optional_date(field: QLineEdit, label: str) -> date | None:
        value = field.text().strip()
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{label} must use YYYY-MM-DD format") from None

    def values(self) -> dict[str, object]:
        notes = self.notes_input.toPlainText()
        return {
            "client_code": self.code_input.text(),
            "company_name": self.company_input.text(),
            "tax_id": self._optional_text(self.tax_id_input),
            "address": self.address_input.text(),
            "city": self.city_input.text(),
            "contact_name": self._optional_text(self.contact_input),
            "phone": self._optional_text(self.phone_input),
            "email": self._optional_text(self.email_input),
            "contract_number": self._optional_text(self.contract_number_input),
            "contract_start": self._optional_date(self.contract_start_input, "Contract start"),
            "contract_end": self._optional_date(self.contract_end_input, "Contract end"),
            "notes": notes if notes.strip() else None,
        }

    def _submit(self) -> None:
        if any(
            not field.text().strip()
            for field in (self.code_input, self.company_input, self.address_input, self.city_input)
        ):
            self.status.show_message("Complete all required fields marked with *.")
            return
        try:
            values = self.values()
        except ValueError as error:
            self.status.show_message(str(error))
            return
        self.status.clear()
        self.save_requested.emit(values)

    def set_busy(self, busy: bool) -> None:
        for field in self.findChildren(QLineEdit) + self.findChildren(QPlainTextEdit):
            field.setEnabled(not busy)
        self.save_button.setEnabled(not busy)
        self.save_button.setText("Saving…" if busy else "Save client")

    def show_error(self, message: str) -> None:
        self.status.show_message(message)
        self.set_busy(False)


class ClientDetailsDialog(QDialog):
    def __init__(
        self,
        client: ClientDTO,
        timezone_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Client {client.client_code}")
        self.setModal(True)
        self.resize(620, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        title = QLabel(client.company_name)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        values = (
            ("Client code", client.client_code),
            ("Status", "Active" if client.active else "Inactive"),
            ("Tax ID", client.tax_id or "—"),
            ("Address", client.address),
            ("City", client.city),
            ("Contact", client.contact_name or "—"),
            ("Phone", client.phone or "—"),
            ("Email", client.email or "—"),
            ("Contract number", client.contract_number or "—"),
            ("Contract start", client.contract_start.isoformat() if client.contract_start else "—"),
            ("Contract end", client.contract_end.isoformat() if client.contract_end else "—"),
            ("Notes", client.notes or "—"),
            ("Created", display_timestamp(client.created_at, timezone_name)),
            ("Updated", display_timestamp(client.updated_at, timezone_name)),
        )
        for label, value in values:
            text = QLabel(value)
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(label, text)
        layout.addLayout(form)
        actions = QHBoxLayout()
        actions.addStretch(1)
        close = QPushButton("Close")
        close.setProperty("secondary", True)
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        layout.addLayout(actions)
