"""Shipment forms and read-only detail views backed by application DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from warehouse_control_center.application.dto import (
    ClientDTO,
    ShipmentDTO,
    ShipmentProblemDTO,
    ShipmentSmsEventDTO,
    ShipmentStatusHistoryDTO,
    ShipmentWeightCheckDTO,
)
from warehouse_control_center.domain.enums import (
    AdditionalServiceType,
    PaymentMethod,
    ProblemType,
    ShipmentPayer,
    ShipmentStatus,
)
from warehouse_control_center.domain.exceptions import InvalidShipmentError
from warehouse_control_center.domain.payment import bam_to_fen, fen_to_bam, validate_payment
from warehouse_control_center.domain.shipment_workflow import can_recover, can_transition
from warehouse_control_center.presentation.qt.dialogs.sms_dialogs import build_sms_history_table
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


def _kilograms_to_grams(value: str, label: str) -> int | None:
    canonical = value.strip()
    if not canonical:
        return None
    try:
        kilograms = Decimal(canonical)
    except InvalidOperation:
        raise ValueError(f"{label} must be a valid number") from None
    grams = kilograms * 1000
    if not kilograms.is_finite() or kilograms <= 0 or grams != grams.to_integral_value():
        raise ValueError(f"{label} must be positive and precise to one gram")
    return int(grams)


def _money_text(value: int | None) -> str:
    amount = fen_to_bam(value)
    return f"{amount:.2f} BAM" if amount is not None else "—"


class PaymentFields(QWidget):
    def __init__(self, shipment: ShipmentDTO | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        form.setSpacing(11)
        self.declared_value_input = _line("shipmentDeclaredValueBam")
        self.declared_value_input.setPlaceholderText("BAM")
        self.cod_enabled_input = QCheckBox("Cash on delivery")
        self.cod_enabled_input.setObjectName("shipmentCodEnabled")
        self.cod_amount_input = _line("shipmentCodAmountBam")
        self.cod_amount_input.setPlaceholderText("BAM")
        self.payer_input = QComboBox()
        self.payer_input.setObjectName("shipmentPayer")
        self.payer_input.addItem("Not specified", None)
        for payer in ShipmentPayer:
            self.payer_input.addItem(display_enum(payer.value), payer.value)
        self.payment_method_input = QComboBox()
        self.payment_method_input.setObjectName("shipmentPaymentMethod")
        self.payment_method_input.addItem("Not specified", None)
        for method in PaymentMethod:
            self.payment_method_input.addItem(display_enum(method.value), method.value)
        form.addRow("Declared value", self.declared_value_input)
        form.addRow("COD", self.cod_enabled_input)
        form.addRow("COD amount", self.cod_amount_input)
        form.addRow("Payer", self.payer_input)
        form.addRow("Payment method", self.payment_method_input)
        self.service_inputs: dict[AdditionalServiceType, QCheckBox] = {}
        services = QWidget()
        services_layout = QVBoxLayout(services)
        services_layout.setContentsMargins(0, 0, 0, 0)
        for service in AdditionalServiceType:
            checkbox = QCheckBox(display_enum(service.value))
            checkbox.setObjectName(f"shipmentService{service.value.title().replace('_', '')}")
            self.service_inputs[service] = checkbox
            services_layout.addWidget(checkbox)
        form.addRow("Additional services", services)
        self.cod_enabled_input.toggled.connect(self._cod_toggled)
        if shipment is not None:
            self._populate(shipment)
        self._cod_toggled(self.cod_enabled_input.isChecked())

    def _populate(self, shipment: ShipmentDTO) -> None:
        declared = fen_to_bam(shipment.declared_value_fen)
        cod = fen_to_bam(shipment.cod_amount_fen)
        self.declared_value_input.setText(f"{declared:.2f}" if declared is not None else "")
        self.cod_enabled_input.setChecked(shipment.cod_enabled)
        self.cod_amount_input.setText(f"{cod:.2f}" if cod is not None else "")
        if shipment.payer is not None:
            self.payer_input.setCurrentIndex(self.payer_input.findData(shipment.payer.value))
        if shipment.payment_method is not None:
            self.payment_method_input.setCurrentIndex(
                self.payment_method_input.findData(shipment.payment_method.value)
            )
        for service in shipment.services:
            self.service_inputs[service].setChecked(True)

    def _cod_toggled(self, checked: bool) -> None:
        self.cod_amount_input.setEnabled(checked)
        if not checked:
            self.cod_amount_input.clear()

    def values(self) -> dict[str, object]:
        try:
            payer_data = self.payer_input.currentData()
            method_data = self.payment_method_input.currentData()
            payer = ShipmentPayer(payer_data) if payer_data else None
            payment_method = PaymentMethod(method_data) if method_data else None
            services = tuple(
                service for service, checkbox in self.service_inputs.items() if checkbox.isChecked()
            )
            payment = validate_payment(
                declared_value_fen=bam_to_fen(
                    self.declared_value_input.text().strip() or None,
                    "Declared value",
                    allow_zero=True,
                ),
                cod_enabled=self.cod_enabled_input.isChecked(),
                cod_amount_fen=bam_to_fen(
                    self.cod_amount_input.text().strip() or None,
                    "COD amount",
                    allow_zero=False,
                ),
                payer=payer,
                payment_method=payment_method,
                services=services,
            )
        except (ValueError, InvalidShipmentError) as error:
            raise ValueError(str(error)) from None
        return {
            "declared_value_fen": payment.declared_value_fen,
            "cod_enabled": payment.cod_enabled,
            "cod_amount_fen": payment.cod_amount_fen,
            "payer": payment.payer,
            "payment_method": payment.payment_method,
            "services": tuple(sorted(payment.services, key=lambda item: item.value)),
        }

    def set_busy(self, busy: bool) -> None:
        for widget in (
            self.declared_value_input,
            self.cod_enabled_input,
            self.cod_amount_input,
            self.payer_input,
            self.payment_method_input,
            *self.service_inputs.values(),
        ):
            widget.setEnabled(not busy)
        if not busy:
            self._cod_toggled(self.cod_enabled_input.isChecked())


class NewShipmentDialog(QDialog):
    create_requested = Signal(object)

    def __init__(
        self,
        clients: tuple[ClientDTO, ...] = (),
        parent: QWidget | None = None,
    ) -> None:
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
        main_tab = QWidget()
        form = QFormLayout(main_tab)
        form.setSpacing(11)
        number_note = QLabel("Shipment number will be generated automatically.")
        number_note.setObjectName("shipmentNumberNote")
        number_note.setWordWrap(True)
        number_note.setProperty("muted", True)
        form.addRow("Numbering", number_note)
        self.client_input = QComboBox()
        self.client_input.setObjectName("shipmentSenderClient")
        self.client_input.setEditable(True)
        self.client_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.client_input.addItem("Walk-in / manual sender", None)
        self._client_names: dict[int, str] = {}
        for client in clients:
            self._client_names[client.id] = client.company_name
            self.client_input.addItem(f"{client.client_code} — {client.company_name}", client.id)
        completer = self.client_input.completer()
        assert completer is not None
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.client_input.currentIndexChanged.connect(self._client_changed)
        self.sender_input = _line("shipmentSender")
        self.recipient_input = _line("shipmentRecipient")
        self.phone_input = _line("shipmentPhone")
        self.address_input = _line("shipmentAddress")
        self.city_input = _line("shipmentCity")
        self.package_count_input = QSpinBox()
        self.package_count_input.setObjectName("shipmentPackageCount")
        self.package_count_input.setRange(1, 2_147_483_647)
        self.length_input = _line("shipmentLengthCm")
        self.width_input = _line("shipmentWidthCm")
        self.height_input = _line("shipmentHeightCm")
        self.declared_weight_input = _line("shipmentDeclaredWeightKg")
        self.declared_weight_input.setPlaceholderText("kg")
        self.notes_input = QPlainTextEdit()
        self.notes_input.setObjectName("shipmentNotes")
        self.notes_input.setMaximumHeight(90)
        for label, field in (
            ("Contract client", self.client_input),
            ("Sender *", self.sender_input),
            ("Recipient *", self.recipient_input),
            ("Phone *", self.phone_input),
            ("Address *", self.address_input),
            ("City *", self.city_input),
            ("Package count *", self.package_count_input),
            ("Length (cm)", self.length_input),
            ("Width (cm)", self.width_input),
            ("Height (cm)", self.height_input),
            ("Declared weight (kg)", self.declared_weight_input),
            ("Notes", self.notes_input),
        ):
            form.addRow(label, field)
        self.payment_fields = PaymentFields()
        tabs = QTabWidget()
        tabs.setObjectName("newShipmentTabs")
        tabs.addTab(main_tab, "Shipment")
        tabs.addTab(self.payment_fields, "Payment & Services")
        layout.addWidget(tabs)
        self.status = StatusBanner()
        layout.addWidget(self.status)
        self.create_button = QPushButton("Create shipment")
        self.create_button.setObjectName("createShipmentAction")
        self.create_button.clicked.connect(self._submit)
        layout.addLayout(_dialog_actions(self, self.create_button))

    def _submit(self) -> None:
        try:
            values = self.values()
        except ValueError as error:
            self.status.show_message(str(error))
            return
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

    def values(self) -> dict[str, object]:
        notes = self.notes_input.toPlainText()
        client_id = self.client_input.currentData()
        return {
            "sender_name": self.sender_input.text(),
            "sender_client_id": client_id if isinstance(client_id, int) else None,
            "recipient_name": self.recipient_input.text(),
            "recipient_phone": self.phone_input.text(),
            "recipient_address": self.address_input.text(),
            "recipient_city": self.city_input.text(),
            "package_count": self.package_count_input.value(),
            "length_cm": self.length_input.text().strip() or None,
            "width_cm": self.width_input.text().strip() or None,
            "height_cm": self.height_input.text().strip() or None,
            "declared_weight_g": _kilograms_to_grams(
                self.declared_weight_input.text(), "Declared weight"
            ),
            "notes": notes if notes.strip() else None,
            **self.payment_fields.values(),
        }

    def _client_changed(self) -> None:
        client_id = self.client_input.currentData()
        selected = isinstance(client_id, int)
        if selected:
            self.sender_input.setText(self._client_names[client_id])
        self.sender_input.setReadOnly(selected)

    def set_busy(self, busy: bool) -> None:
        for field in (
            self.client_input,
            self.sender_input,
            self.recipient_input,
            self.phone_input,
            self.address_input,
            self.city_input,
            self.package_count_input,
            self.length_input,
            self.width_input,
            self.height_input,
            self.declared_weight_input,
            self.notes_input,
        ):
            field.setEnabled(not busy)
        self.create_button.setEnabled(not busy)
        self.payment_fields.set_busy(busy)
        self.create_button.setText("Creating…" if busy else "Create shipment")

    def show_error(self, message: str) -> None:
        self.status.show_message(message)
        self.set_busy(False)


class ControlWeightDialog(QDialog):
    record_requested = Signal(int, object)

    def __init__(self, shipment: ShipmentDTO, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Control weight")
        self.setModal(True)
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        title = QLabel(f"Control weight — {shipment.shipment_number}")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        declared = (
            f"{Decimal(shipment.declared_weight_g) / 1000} kg"
            if shipment.declared_weight_g is not None
            else "Not declared"
        )
        form.addRow("Declared weight", QLabel(declared))
        self.measured_input = _line("shipmentMeasuredWeightKg")
        self.measured_input.setPlaceholderText("kg")
        self.note_input = QPlainTextEdit()
        self.note_input.setObjectName("shipmentWeightNote")
        self.note_input.setMaximumHeight(90)
        form.addRow("Measured weight (kg) *", self.measured_input)
        form.addRow("Note", self.note_input)
        layout.addLayout(form)
        self.status = StatusBanner()
        layout.addWidget(self.status)
        self.record_button = QPushButton("Record weight")
        self.record_button.setObjectName("recordShipmentWeightAction")
        self.record_button.clicked.connect(self._submit)
        layout.addLayout(_dialog_actions(self, self.record_button))

    def _submit(self) -> None:
        try:
            grams = _kilograms_to_grams(self.measured_input.text(), "Measured weight")
        except ValueError as error:
            self.status.show_message(str(error))
            return
        if grams is None:
            self.status.show_message("Measured weight is required.")
            return
        note = self.note_input.toPlainText()
        self.status.clear()
        self.record_requested.emit(grams, note if note.strip() else None)

    def set_busy(self, busy: bool) -> None:
        self.measured_input.setEnabled(not busy)
        self.note_input.setEnabled(not busy)
        self.record_button.setEnabled(not busy)
        self.record_button.setText("Recording…" if busy else "Record weight")

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
        title = QLabel(f"Edit {shipment.shipment_number}")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        main_tab = QWidget()
        form = QFormLayout(main_tab)
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
        self.payment_fields = PaymentFields(shipment)
        tabs = QTabWidget()
        tabs.setObjectName("editShipmentTabs")
        tabs.addTab(main_tab, "Shipment")
        tabs.addTab(self.payment_fields, "Payment & Services")
        layout.addWidget(tabs)
        self.status = StatusBanner()
        layout.addWidget(self.status)
        self.save_button = QPushButton("Save changes")
        self.save_button.setObjectName("saveShipmentAction")
        self.save_button.clicked.connect(self._submit)
        layout.addLayout(_dialog_actions(self, self.save_button))

    def _submit(self) -> None:
        try:
            values = self.values()
        except ValueError as error:
            self.status.show_message(str(error))
            return
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

    def values(self) -> dict[str, object]:
        notes = self.notes_input.toPlainText()
        return {
            "sender_name": self.sender_input.text(),
            "recipient_name": self.recipient_input.text(),
            "recipient_phone": self.phone_input.text(),
            "recipient_address": self.address_input.text(),
            "recipient_city": self.city_input.text(),
            "notes": notes if notes.strip() else None,
            **self.payment_fields.values(),
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
        self.payment_fields.set_busy(busy)
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
    weight_checks: tuple[ShipmentWeightCheckDTO, ...] = ()
    sms_events: tuple[ShipmentSmsEventDTO, ...] = ()


class ShipmentDetailsDialog(QDialog):
    def __init__(
        self,
        details: ShipmentDetailsData,
        timezone_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        shipment = details.shipment
        self.setWindowTitle(f"Shipment {shipment.shipment_number}")
        self.setModal(True)
        self.resize(780, 600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        title = QLabel(f"Shipment {shipment.shipment_number}")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        tabs = QTabWidget()
        tabs.setObjectName("shipmentDetailsTabs")
        tabs.addTab(self._details_tab(shipment, timezone_name), "Details")
        if self._has_payment_details(shipment):
            tabs.addTab(self._payment_tab(shipment), "Payment & Services")
        tabs.addTab(self._history_tab(details.history, timezone_name), "History")
        tabs.addTab(self._problem_tab(details.problem, timezone_name), "Problem")
        tabs.addTab(
            self._weight_history_tab(details.weight_checks, timezone_name),
            "Weight history",
        )
        tabs.addTab(self._sms_history_tab(details.sms_events, timezone_name), "SMS History")
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
            ("Shipment number", shipment.shipment_number),
            ("Status", display_enum(shipment.status.value)),
            ("Sender", shipment.sender_name),
            ("Contract client ID", str(shipment.sender_client_id or "—")),
            ("Packages", str(shipment.package_count)),
            ("Length", f"{shipment.length_cm} cm" if shipment.length_cm else "—"),
            ("Width", f"{shipment.width_cm} cm" if shipment.width_cm else "—"),
            ("Height", f"{shipment.height_cm} cm" if shipment.height_cm else "—"),
            (
                "Declared weight",
                f"{Decimal(shipment.declared_weight_g) / 1000} kg"
                if shipment.declared_weight_g is not None
                else "—",
            ),
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
    def _has_payment_details(shipment: ShipmentDTO) -> bool:
        return any(
            (
                shipment.declared_value_fen is not None,
                shipment.cod_enabled,
                shipment.payer is not None,
                shipment.payment_method is not None,
                bool(shipment.services),
            )
        )

    @staticmethod
    def _payment_tab(shipment: ShipmentDTO) -> QWidget:
        tab = QWidget()
        tab.setObjectName("shipmentPaymentDetails")
        form = QFormLayout(tab)
        values: list[tuple[str, str]] = []
        if shipment.declared_value_fen is not None:
            values.append(("Declared value", _money_text(shipment.declared_value_fen)))
        if shipment.cod_enabled:
            values.extend(
                (
                    ("Cash on delivery", "Yes"),
                    ("COD amount", _money_text(shipment.cod_amount_fen)),
                )
            )
        if shipment.payer is not None:
            values.append(("Payer", display_enum(shipment.payer.value)))
        if shipment.payment_method is not None:
            values.append(("Payment method", display_enum(shipment.payment_method.value)))
        if shipment.services:
            values.append(
                (
                    "Additional services",
                    ", ".join(display_enum(service.value) for service in shipment.services),
                )
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

    @staticmethod
    def _weight_history_tab(
        checks: tuple[ShipmentWeightCheckDTO, ...], timezone_name: str
    ) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        table = QTableWidget(len(checks), 8)
        table.setObjectName("shipmentWeightHistoryTable")
        table.setHorizontalHeaderLabels(
            (
                "Checked at",
                "Declared (kg)",
                "Measured (kg)",
                "Difference (g)",
                "Tolerance (g)",
                "Result",
                "Checked by",
                "Note",
            )
        )
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        for row, check in enumerate(checks):
            values = (
                display_timestamp(check.checked_at, timezone_name),
                str(Decimal(check.declared_weight_g_snapshot) / 1000),
                str(Decimal(check.measured_weight_g) / 1000),
                str(check.absolute_difference_g),
                str(check.tolerance_abs_g_snapshot),
                display_enum(check.result.value),
                str(check.checked_by_user_id),
                check.note or "—",
            )
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        return tab

    @staticmethod
    def _sms_history_tab(events: tuple[ShipmentSmsEventDTO, ...], timezone_name: str) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        if not events:
            layout.addWidget(QLabel("No SMS history."))
        layout.addWidget(build_sms_history_table(events, timezone_name), 1)
        return tab
