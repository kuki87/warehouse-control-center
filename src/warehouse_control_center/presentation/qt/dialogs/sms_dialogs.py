"""Shipment SMS recording and append-only history dialogs."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
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
    QVBoxLayout,
    QWidget,
)

from warehouse_control_center.application.dto import ShipmentDTO, ShipmentSmsEventDTO
from warehouse_control_center.domain.enums import (
    SmsMessageType,
    SmsSenderType,
    SmsSendStatus,
)
from warehouse_control_center.presentation.qt.shipment_formatting import (
    display_enum,
    display_timestamp,
)
from warehouse_control_center.presentation.qt.widgets.status_banner import StatusBanner


class RecordSmsDialog(QDialog):
    record_requested = Signal(object)

    def __init__(self, shipment: ShipmentDTO, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Record SMS — {shipment.shipment_number}")
        self.setModal(True)
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(14)
        title = QLabel("Record SMS activity")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        note = QLabel(
            "This records SMS activity only. No message is transmitted by this application."
        )
        note.setWordWrap(True)
        note.setProperty("muted", True)
        note.setObjectName("smsRecordingNotice")
        layout.addWidget(note)
        form = QFormLayout()
        self.sender_input = QComboBox()
        self.sender_input.setObjectName("smsSenderType")
        for sender in SmsSenderType:
            self.sender_input.addItem(display_enum(sender.value), sender.value)
        self.sender_input.setCurrentIndex(self.sender_input.findData(SmsSenderType.WAREHOUSE.value))
        self.message_type_input = QComboBox()
        self.message_type_input.setObjectName("smsMessageType")
        for message_type in SmsMessageType:
            self.message_type_input.addItem(display_enum(message_type.value), message_type.value)
        self.phone_input = QLineEdit(shipment.recipient_phone)
        self.phone_input.setObjectName("smsPhone")
        self.message_input = QPlainTextEdit()
        self.message_input.setObjectName("smsMessageText")
        self.message_input.setMaximumHeight(130)
        self.message_input.setPlaceholderText(
            "Required for Custom; predefined types use a centralized template when blank."
        )
        self.status_input = QComboBox()
        self.status_input.setObjectName("smsSendStatus")
        self.status_input.addItem("Recorded (not transmitted)", SmsSendStatus.RECORDED.value)
        form.addRow("Sender type *", self.sender_input)
        form.addRow("Message type *", self.message_type_input)
        form.addRow("Phone *", self.phone_input)
        form.addRow("Message text", self.message_input)
        form.addRow("Status", self.status_input)
        layout.addLayout(form)
        self.status = StatusBanner()
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setProperty("secondary", True)
        cancel.clicked.connect(self.reject)
        self.record_button = QPushButton("Record SMS")
        self.record_button.setObjectName("recordSmsAction")
        self.record_button.clicked.connect(self._submit)
        actions.addWidget(cancel)
        actions.addWidget(self.record_button)
        layout.addLayout(actions)

    def _submit(self) -> None:
        message_type = SmsMessageType(self.message_type_input.currentData())
        message = self.message_input.toPlainText()
        if message_type is SmsMessageType.CUSTOM and not message.strip():
            self.status.show_message("Custom SMS message text is required.")
            return
        if not self.phone_input.text().strip():
            self.status.show_message("SMS phone is required.")
            return
        self.status.clear()
        self.record_requested.emit(
            {
                "sender_type": SmsSenderType(self.sender_input.currentData()),
                "message_type": message_type,
                "phone_number": self.phone_input.text(),
                "message_text": message if message.strip() else None,
                "send_status": SmsSendStatus(self.status_input.currentData()),
            }
        )

    def set_busy(self, busy: bool) -> None:
        for field in (
            self.sender_input,
            self.message_type_input,
            self.phone_input,
            self.message_input,
            self.status_input,
        ):
            field.setEnabled(not busy)
        self.record_button.setEnabled(not busy)
        self.record_button.setText("Recording…" if busy else "Record SMS")

    def show_error(self, message: str) -> None:
        self.status.show_message(message)
        self.set_busy(False)


def build_sms_history_table(
    events: tuple[ShipmentSmsEventDTO, ...], timezone_name: str
) -> QTableWidget:
    table = QTableWidget(len(events), 7)
    table.setObjectName("shipmentSmsHistoryTable")
    table.setHorizontalHeaderLabels(
        ("Timestamp", "Sender", "Message type", "Phone", "Status", "Recorded by", "Message")
    )
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    for row, event in enumerate(events):
        values = (
            display_timestamp(event.sent_at, timezone_name),
            display_enum(event.sender_type.value),
            display_enum(event.message_type.value),
            event.phone_number,
            display_enum(event.send_status.value),
            str(event.sent_by_user_id) if event.sent_by_user_id is not None else "System",
            event.message_text,
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 6:
                item.setToolTip(value)
            table.setItem(row, column, item)
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)
    return table


class ShipmentSmsHistoryDialog(QDialog):
    def __init__(
        self,
        shipment_number: str,
        events: tuple[ShipmentSmsEventDTO, ...],
        timezone_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"SMS history — {shipment_number}")
        self.setModal(True)
        self.resize(960, 520)
        layout = QVBoxLayout(self)
        title = QLabel(f"SMS history — {shipment_number}")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        if not events:
            layout.addWidget(QLabel("No SMS history."))
        layout.addWidget(build_sms_history_table(events, timezone_name), 1)
        close = QPushButton("Close")
        close.setProperty("secondary", True)
        close.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(close)
        layout.addLayout(actions)
