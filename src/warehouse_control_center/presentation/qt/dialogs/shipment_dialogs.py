"""Shipment forms and read-only detail views backed by application DTOs."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from warehouse_control_center.application.dto import (
    ShipmentDTO,
    ShipmentProblemDTO,
    ShipmentStatusHistoryDTO,
)
from warehouse_control_center.domain.enums import ProblemType, ShipmentStatus
from warehouse_control_center.domain.shipment_workflow import can_recover, can_transition
from warehouse_control_center.presentation.qt.shipment_formatting import (
    display_enum,
    display_timestamp,
)
from warehouse_control_center.presentation.qt.widgets.status_banner import StatusBanner


def _line(name: str) -> QLineEdit:
    field = QLineEdit()
    field.setObjectName(name)
    return field


def _dialog_actions(dialog: QDialog, submit: QPushButton) -> QHBoxLayout:
    actions = QHBoxLayout()
    actions.addStretch(1)
    cancel = QPushButton("Cancel")
    cancel.setProperty("secondary", True)
    cancel.clicked.connect(dialog.reject)
    actions.addWidget(cancel)
    actions.addWidget(submit)
    return actions


class NewShipmentDialog(QDialog):
    create_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New shipment")
        self.setModal(True)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(14)
        title = QLabel("New shipment")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.setSpacing(11)
        number_note = QLabel("Shipment number and barcode will be generated automatically.")
        number_note.setObjectName("shipmentNumberNote")
        number_note.setWordWrap(True)
        number_note.setProperty("muted", True)
        form.addRow("Numbering", number_note)
        self.sender_input = _line("shipmentSender")
        self.recipient_input = _line("shipmentRecipient")
        self.phone_input = _line("shipmentPhone")
        self.address_input = _line("shipmentAddress")
        self.city_input = _line("shipmentCity")
        self.notes_input = QPlainTextEdit()
        self.notes_input.setObjectName("shipmentNotes")
        self.notes_input.setMaximumHeight(90)
        for label, field in (
            ("Sender *", self.sender_input),
            ("Recipient *", self.recipient_input),
            ("Phone *", self.phone_input),
            ("Address *", self.address_input),
            ("City *", self.city_input),
            ("Notes", self.notes_input),
        ):
            form.addRow(label, field)
        layout.addLayout(form)
        self.status = StatusBanner()
        layout.addWidget(self.status)
        self.create_button = QPushButton("Create shipment")
        self.create_button.setObjectName("createShipmentAction")
        self.create_button.clicked.connect(self._submit)
        layout.addLayout(_dialog_actions(self, self.create_button))

    def _submit(self) -> None:
        values = self.values()
        required = (
            "sender_name",
            "recipient_name",
            "recipient_phone",
            "recipient_address",
            "recipient_city",
        )
        if any(not str(values[name]).strip() for name in required):
            self.status.show_message("Complete all required fields marked with *.")
            return
        self.status.clear()
        self.create_requested.emit(values)

    def values(self) -> dict[str, str | None]:
        notes = self.notes_input.toPlainText()
        return {
            "sender_name": self.sender_input.text(),
            "recipient_name": self.recipient_input.text(),
            "recipient_phone": self.phone_input.text(),
            "recipient_address": self.address_input.text(),
            "recipient_city": self.city_input.text(),
            "notes": notes if notes.strip() else None,
        }

    def set_busy(self, busy: bool) -> None:
        for field in (
            self.sender_input,
            self.recipient_input,
            self.phone_input,
            self.address_input,
            self.city_input,
            self.notes_input,
        ):
            field.setEnabled(not busy)
        self.create_button.setEnabled(not busy)
        self.create_button.setText("Creating…" if busy else "Create shipment")

    def show_error(self, message: str) -> None:
        self.status.show_message(message)
        self.set_busy(False)


class EditShipmentDialog(QDialog):
    update_requested = Signal(object)

    def __init__(self, shipment: ShipmentDTO, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.shipment = shipment
        self.setWindowTitle("Edit shipment")
        self.setModal(True)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(14)
        title = QLabel(f"Edit {shipment.tracking_number}")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.setSpacing(11)
        self.sender_input = _line("editShipmentSender")
        self.recipient_input = _line("editShipmentRecipient")
        self.phone_input = _line("editShipmentPhone")
        self.address_input = _line("editShipmentAddress")
        self.city_input = _line("editShipmentCity")
        self.notes_input = QPlainTextEdit()
        self.notes_input.setObjectName("editShipmentNotes")
        self.notes_input.setMaximumHeight(90)
        self.sender_input.setText(shipment.sender_name)
        self.recipient_input.setText(shipment.recipient_name)
        self.phone_input.setText(shipment.recipient_phone)
        self.address_input.setText(shipment.recipient_address)
        self.city_input.setText(shipment.recipient_city)
        self.notes_input.setPlainText(shipment.notes or "")
        for label, field in (
            ("Sender *", self.sender_input),
            ("Recipient *", self.recipient_input),
            ("Phone *", self.phone_input),
            ("Address *", self.address_input),
            ("City *", self.city_input),
            ("Notes", self.notes_input),
        ):
            form.addRow(label, field)
        layout.addLayout(form)
        self.status = StatusBanner()
        layout.addWidget(self.status)
        self.save_button = QPushButton("Save changes")
        self.save_button.setObjectName("saveShipmentAction")
        self.save_button.clicked.connect(self._submit)
        layout.addLayout(_dialog_actions(self, self.save_button))

    def _submit(self) -> None:
        values = self.values()
        required = (
            "sender_name",
            "recipient_name",
            "recipient_phone",
            "recipient_address",
            "recipient_city",
        )
        if any(not str(values[name]).strip() for name in required):
            self.status.show_message("Complete all required fields marked with *.")
            return
        self.status.clear()
        self.update_requested.emit(values)

    def values(self) -> dict[str, str | None]:
        notes = self.notes_input.toPlainText()
        return {
            "sender_name": self.sender_input.text(),
            "recipient_name": self.recipient_input.text(),
            "recipient_phone": self.phone_input.text(),
            "recipient_address": self.address_input.text(),
            "recipient_city": self.city_input.text(),
            "notes": notes if notes.strip() else None,
        }

    def set_busy(self, busy: bool) -> None:
        for field in (
            self.sender_input,
            self.recipient_input,
            self.phone_input,
            self.address_input,
            self.city_input,
            self.notes_input,
        ):
            field.setEnabled(not busy)
        self.save_button.setEnabled(not busy)
        self.save_button.setText("Saving…" if busy else "Save changes")

    def show_error(self, message: str) -> None:
        self.status.show_message(message)
        self.set_busy(False)


class ChangeStatusDialog(QDialog):
    change_requested = Signal(object, str, bool)

    def __init__(
        self,
        shipment: ShipmentDTO,
        *,
        allow_override: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._shipment = shipment
        self._allow_override = allow_override
        self.setWindowTitle("Change shipment status")
        self.setModal(True)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(14)
        title = QLabel("Change status")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.addRow("Current status", QLabel(display_enum(shipment.status.value)))
        self.target_input = QComboBox()
        self.target_input.setObjectName("shipmentTargetStatus")
        form.addRow("New status", self.target_input)
        self.override_input = QCheckBox("Use administrator override")
        self.override_input.setObjectName("shipmentStatusOverride")
        self.override_input.setVisible(allow_override)
        self.override_input.toggled.connect(self._populate_targets)
        form.addRow("", self.override_input)
        self.reason_input = QPlainTextEdit()
        self.reason_input.setObjectName("shipmentStatusReason")
        self.reason_input.setMaximumHeight(85)
        form.addRow("Reason", self.reason_input)
        layout.addLayout(form)
        self.status = StatusBanner()
        layout.addWidget(self.status)
        self.change_button = QPushButton("Change status")
        self.change_button.setObjectName("changeShipmentStatusAction")
        self.change_button.clicked.connect(self._submit)
        layout.addLayout(_dialog_actions(self, self.change_button))
        self._populate_targets()

    def _populate_targets(self) -> None:
        selected = self.target_input.currentData()
        override = self._allow_override and self.override_input.isChecked()
        self.target_input.clear()
        for target in ShipmentStatus:
            if target in {self._shipment.status, ShipmentStatus.PROBLEM}:
                continue
            if override or can_transition(self._shipment.status, target):
                self.target_input.addItem(display_enum(target.value), target.value)
        index = self.target_input.findData(selected)
        if index >= 0:
            self.target_input.setCurrentIndex(index)
        self.change_button.setEnabled(self.target_input.count() > 0)

    def _submit(self) -> None:
        try:
            target = ShipmentStatus(self.target_input.currentData())
        except (TypeError, ValueError):
            self.status.show_message("No valid status transition is available.")
            return
        override = self._allow_override and self.override_input.isChecked()
        reason = self.reason_input.toPlainText()
        if override and not reason.strip():
            self.status.show_message("An override reason is required.")
            return
        self.status.clear()
        self.change_requested.emit(target, reason, override)

    def set_busy(self, busy: bool) -> None:
        self.target_input.setEnabled(not busy)
        self.override_input.setEnabled(not busy)
        self.reason_input.setEnabled(not busy)
        self.change_button.setEnabled(not busy and self.target_input.count() > 0)
        self.change_button.setText("Changing…" if busy else "Change status")

    def show_error(self, message: str) -> None:
        self.status.show_message(message)
        self.set_busy(False)


class ReportProblemDialog(QDialog):
    report_requested = Signal(object, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Report shipment problem")
        self.setModal(True)
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(14)
        title = QLabel("Report problem")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        self.type_input = QComboBox()
        self.type_input.setObjectName("shipmentProblemType")
        for problem_type in ProblemType:
            self.type_input.addItem(display_enum(problem_type.value), problem_type.value)
        self.description_input = QPlainTextEdit()
        self.description_input.setObjectName("shipmentProblemDescription")
        self.description_input.setMaximumHeight(110)
        form.addRow("Problem type", self.type_input)
        form.addRow("Description", self.description_input)
        layout.addLayout(form)
        self.status = StatusBanner()
        layout.addWidget(self.status)
        self.report_button = QPushButton("Report problem")
        self.report_button.setObjectName("reportShipmentProblemAction")
        self.report_button.clicked.connect(self._submit)
        layout.addLayout(_dialog_actions(self, self.report_button))

    def _submit(self) -> None:
        try:
            problem_type = ProblemType(self.type_input.currentData())
        except (TypeError, ValueError):
            self.status.show_message("Choose a valid problem type.")
            return
        description = self.description_input.toPlainText()
        if problem_type is ProblemType.OTHER and not description.strip():
            self.status.show_message("Describe an Other problem.")
            return
        self.status.clear()
        self.report_requested.emit(problem_type, description)

    def set_busy(self, busy: bool) -> None:
        self.type_input.setEnabled(not busy)
        self.description_input.setEnabled(not busy)
        self.report_button.setEnabled(not busy)
        self.report_button.setText("Reporting…" if busy else "Report problem")

    def show_error(self, message: str) -> None:
        self.status.show_message(message)
        self.set_busy(False)


class ResolveProblemDialog(QDialog):
    resolve_requested = Signal(object, str)

    def __init__(
        self,
        problem: ShipmentProblemDTO,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resolve shipment problem")
        self.setModal(True)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(14)
        title = QLabel("Resolve problem")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        summary = QLabel(
            f"{display_enum(problem.problem_type.value)} — "
            f"{problem.description or 'No description'}"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        form = QFormLayout()
        self.recovery_input = QComboBox()
        self.recovery_input.setObjectName("shipmentRecoveryStatus")
        for target in ShipmentStatus:
            if can_recover(problem.previous_status, target):
                self.recovery_input.addItem(display_enum(target.value), target.value)
        default_index = self.recovery_input.findData(problem.previous_status.value)
        if default_index >= 0:
            self.recovery_input.setCurrentIndex(default_index)
        self.reason_input = QPlainTextEdit()
        self.reason_input.setObjectName("shipmentRecoveryReason")
        self.reason_input.setMaximumHeight(90)
        form.addRow("Recovery status", self.recovery_input)
        form.addRow("Resolution note", self.reason_input)
        layout.addLayout(form)
        self.status = StatusBanner()
        layout.addWidget(self.status)
        self.resolve_button = QPushButton("Resolve problem")
        self.resolve_button.setObjectName("resolveShipmentProblemAction")
        self.resolve_button.clicked.connect(self._submit)
        layout.addLayout(_dialog_actions(self, self.resolve_button))

    def _submit(self) -> None:
        try:
            target = ShipmentStatus(self.recovery_input.currentData())
        except (TypeError, ValueError):
            self.status.show_message("Choose a valid recovery status.")
            return
        self.status.clear()
        self.resolve_requested.emit(target, self.reason_input.toPlainText())

    def set_busy(self, busy: bool) -> None:
        self.recovery_input.setEnabled(not busy)
        self.reason_input.setEnabled(not busy)
        self.resolve_button.setEnabled(not busy)
        self.resolve_button.setText("Resolving…" if busy else "Resolve problem")

    def show_error(self, message: str) -> None:
        self.status.show_message(message)
        self.set_busy(False)


@dataclass(frozen=True, slots=True)
class ShipmentDetailsData:
    shipment: ShipmentDTO
    history: tuple[ShipmentStatusHistoryDTO, ...]
    problem: ShipmentProblemDTO | None


class ShipmentDetailsDialog(QDialog):
    def __init__(
        self,
        details: ShipmentDetailsData,
        timezone_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        shipment = details.shipment
        self.setWindowTitle(f"Shipment {shipment.tracking_number}")
        self.setModal(True)
        self.resize(780, 600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        title = QLabel(f"Shipment {shipment.tracking_number}")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        tabs = QTabWidget()
        tabs.setObjectName("shipmentDetailsTabs")
        tabs.addTab(self._details_tab(shipment, timezone_name), "Details")
        tabs.addTab(self._history_tab(details.history, timezone_name), "History")
        tabs.addTab(self._problem_tab(details.problem, timezone_name), "Problem")
        layout.addWidget(tabs, 1)
        close_button = QPushButton("Close")
        close_button.setProperty("secondary", True)
        close_button.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(close_button)
        layout.addLayout(actions)

    @staticmethod
    def _details_tab(shipment: ShipmentDTO, timezone_name: str) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        values = (
            ("Tracking number", shipment.tracking_number),
            ("Barcode", shipment.barcode),
            ("Status", display_enum(shipment.status.value)),
            ("Sender", shipment.sender_name),
            ("Recipient", shipment.recipient_name),
            ("Phone", shipment.recipient_phone),
            ("Address", shipment.recipient_address),
            ("City", shipment.recipient_city),
            ("Courier", str(shipment.courier_id) if shipment.courier_id else "Unassigned"),
            ("Notes", shipment.notes or "—"),
            ("Received", display_timestamp(shipment.received_at, timezone_name)),
            ("Created", display_timestamp(shipment.created_at, timezone_name)),
            ("Updated", display_timestamp(shipment.updated_at, timezone_name)),
            ("Archived", display_timestamp(shipment.archived_at, timezone_name)),
        )
        for label, value in values:
            text = QLabel(value)
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(label, text)
        return tab

    @staticmethod
    def _history_tab(history: tuple[ShipmentStatusHistoryDTO, ...], timezone_name: str) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        table = QTableWidget(len(history), 6)
        table.setObjectName("shipmentHistoryTable")
        table.setHorizontalHeaderLabels(
            ("Previous", "New", "Changed at", "Changed by", "Override", "Reason")
        )
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        for row, item in enumerate(history):
            values = (
                display_enum(item.old_status.value),
                display_enum(item.new_status.value),
                display_timestamp(item.timestamp, timezone_name),
                str(item.changed_by),
                "Yes" if item.is_admin_override else "No",
                item.reason or "—",
            )
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        return tab

    @staticmethod
    def _problem_tab(problem: ShipmentProblemDTO | None, timezone_name: str) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        if problem is None:
            form.addRow(QLabel("No unresolved problem."))
            return tab
        values = (
            ("Type", display_enum(problem.problem_type.value)),
            ("Description", problem.description or "—"),
            ("Previous status", display_enum(problem.previous_status.value)),
            ("Reported at", display_timestamp(problem.reported_at, timezone_name)),
            ("Reported by", str(problem.reported_by)),
            ("Resolved", "No"),
        )
        for label, value in values:
            text = QLabel(value)
            text.setWordWrap(True)
            form.addRow(label, text)
        return tab
