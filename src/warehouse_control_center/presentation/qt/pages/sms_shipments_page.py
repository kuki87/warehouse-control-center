"""Paginated overview of shipments having append-only SMS history."""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum
from math import ceil
from typing import cast

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from warehouse_control_center.application.dto import (
    SessionContext,
    ShipmentSmsEventPage,
    ShipmentSmsSummaryDTO,
    ShipmentSmsSummaryPage,
)
from warehouse_control_center.application.services import ShipmentSmsService
from warehouse_control_center.domain.enums import (
    SmsMessageType,
    SmsSenderType,
    SmsSendStatus,
)
from warehouse_control_center.presentation.qt.dialogs.sms_dialogs import (
    ShipmentSmsHistoryDialog,
)
from warehouse_control_center.presentation.qt.error_mapping import (
    log_unexpected,
    translate_error,
)
from warehouse_control_center.presentation.qt.shipment_formatting import (
    display_enum,
    display_timestamp,
)
from warehouse_control_center.presentation.qt.widgets.status_banner import StatusBanner
from warehouse_control_center.presentation.qt.workers import DatabaseTaskRunner


class SmsShipmentsPage(QWidget):
    session_invalidated = Signal()

    _HEADERS = (
        "Shipment Number",
        "Recipient",
        "Phone",
        "City",
        "SMS Count",
        "Last SMS At",
        "Last Sender Type",
        "Last Message Type",
        "Last Status",
    )

    def __init__(
        self,
        session: SessionContext,
        sms: ShipmentSmsService,
        thread_pool: QThreadPool,
        logger: logging.Logger,
        timezone_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("sms_shipments_page")
        self._session = session
        self._sms = sms
        self._logger = logger
        self._timezone_name = timezone_name
        self._tasks = DatabaseTaskRunner(thread_pool, self)
        self._records: dict[int, ShipmentSmsSummaryDTO] = {}
        self._page = 1
        self._total = 0
        self._busy = False
        self._history_dialog: ShipmentSmsHistoryDialog | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        title_row = QHBoxLayout()
        title = QLabel("SMS Shipments")
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.refresh_button = self._button(
            "Refresh", "refreshSmsShipments", self.refresh, secondary=True
        )
        title_row.addWidget(self.refresh_button)
        layout.addLayout(title_row)
        self.status = StatusBanner()
        layout.addWidget(self.status)
        layout.addWidget(self._build_filters())

        self.table = QTableWidget(0, len(self._HEADERS))
        self.table.setObjectName("smsShipmentsTable")
        self.table.setHorizontalHeaderLabels(self._HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.table.cellDoubleClicked.connect(lambda row, column: self.open_history())
        layout.addWidget(self.table, 1)

        pagination = QHBoxLayout()
        self.previous_button = self._button(
            "Previous", "previousSmsShipmentPage", self.previous_page, secondary=True
        )
        self.next_button = self._button(
            "Next", "nextSmsShipmentPage", self.next_page, secondary=True
        )
        self.page_label = QLabel("Page 1 of 1 • 0 results")
        self.page_label.setObjectName("smsShipmentPageSummary")
        self.page_size_input = QComboBox()
        self.page_size_input.setObjectName("smsShipmentPageSize")
        for size in (25, 50, 100):
            self.page_size_input.addItem(f"{size} per page", size)
        self.page_size_input.setCurrentIndex(1)
        self.page_size_input.currentIndexChanged.connect(self._page_size_changed)
        pagination.addWidget(self.previous_button)
        pagination.addWidget(self.next_button)
        pagination.addWidget(self.page_label)
        pagination.addStretch(1)
        pagination.addWidget(self.page_size_input)
        layout.addLayout(pagination)

        actions = QHBoxLayout()
        self.history_button = self._button("Open SMS History", "openSmsHistory", self.open_history)
        actions.addWidget(self.history_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self._update_actions()
        QTimer.singleShot(0, self.refresh)

    def _build_filters(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("filterCard")
        form = QFormLayout(frame)
        row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setObjectName("smsShipmentSearch")
        self.search_input.setPlaceholderText("Shipment number, recipient, phone, city…")
        self.search_input.returnPressed.connect(self.apply_filters)
        row.addWidget(self.search_input, 2)
        self.sender_input = self._enum_filter("smsSenderFilter", "All senders", SmsSenderType)
        self.message_input = self._enum_filter(
            "smsMessageFilter", "All message types", SmsMessageType
        )
        self.status_input = self._enum_filter("smsStatusFilter", "All statuses", SmsSendStatus)
        row.addWidget(self.sender_input)
        row.addWidget(self.message_input)
        row.addWidget(self.status_input)
        self.apply_button = self._button("Apply", "applySmsFilters", self.apply_filters)
        self.clear_button = self._button(
            "Clear", "clearSmsFilters", self.clear_filters, secondary=True
        )
        row.addWidget(self.apply_button)
        row.addWidget(self.clear_button)
        form.addRow(row)
        return frame

    @staticmethod
    def _enum_filter(name: str, empty_label: str, enum_type: type[StrEnum]) -> QComboBox:
        field = QComboBox()
        field.setObjectName(name)
        field.addItem(empty_label, None)
        for value in enum_type:
            field.addItem(display_enum(value.value), value.value)
        return field

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
        if self._busy:
            return
        self._set_busy(True)
        self.status.clear()
        sender = self.sender_input.currentData()
        message = self.message_input.currentData()
        status = self.status_input.currentData()
        self._tasks.submit(
            lambda: self._sms.list_shipments_with_sms(
                self._session,
                page=self._page,
                page_size=cast(int, self.page_size_input.currentData()),
                search=self.search_input.text() or None,
                sender_type=SmsSenderType(sender) if sender else None,
                message_type=SmsMessageType(message) if message else None,
                send_status=SmsSendStatus(status) if status else None,
            ),
            on_result=self._populate,
            on_error=lambda error: self._handle_error(error, "load SMS shipments"),
            on_finished=lambda: self._set_busy(False),
        )

    def _populate(self, result: object) -> None:
        page = cast(ShipmentSmsSummaryPage, result)
        self._total = page.total
        self._records = {item.shipment.id: item for item in page.items}
        self.table.setRowCount(len(page.items))
        for row, summary in enumerate(page.items):
            shipment = summary.shipment
            event = summary.last_event
            values = (
                shipment.shipment_number,
                shipment.recipient_name,
                shipment.recipient_phone,
                shipment.recipient_city,
                str(summary.sms_count),
                display_timestamp(event.sent_at, self._timezone_name),
                display_enum(event.sender_type.value),
                display_enum(event.message_type.value),
                display_enum(event.send_status.value),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, shipment.id)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        if not page.items:
            self.status.show_message("No shipments with SMS history found.", status="warning")
        self._update_page_summary()
        self._update_actions()

    def selected_summary(self) -> ShipmentSmsSummaryDTO | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        shipment_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return self._records.get(shipment_id) if isinstance(shipment_id, int) else None

    def open_history(self) -> None:
        summary = self.selected_summary()
        if summary is None or self._busy:
            return
        self._set_busy(True)
        self._tasks.submit(
            lambda: self._sms.list_sms_for_shipment(
                self._session, summary.shipment.id, page_size=100
            ),
            on_result=lambda result: self._show_history(summary, result),
            on_error=lambda error: self._handle_error(error, "load SMS history"),
            on_finished=lambda: self._set_busy(False),
        )

    def _show_history(self, summary: ShipmentSmsSummaryDTO, result: object) -> None:
        events = cast(ShipmentSmsEventPage, result).items
        self._history_dialog = ShipmentSmsHistoryDialog(
            summary.shipment.shipment_number, events, self._timezone_name, self
        )
        self._history_dialog.open()

    def apply_filters(self) -> None:
        self._page = 1
        self.refresh()

    def clear_filters(self) -> None:
        self.search_input.clear()
        self.sender_input.setCurrentIndex(0)
        self.message_input.setCurrentIndex(0)
        self.status_input.setCurrentIndex(0)
        self.apply_filters()

    def previous_page(self) -> None:
        if self._page > 1:
            self._page -= 1
            self.refresh()

    def next_page(self) -> None:
        pages = max(1, ceil(self._total / cast(int, self.page_size_input.currentData())))
        if self._page < pages:
            self._page += 1
            self.refresh()

    def _page_size_changed(self) -> None:
        self._page = 1
        self.refresh()

    def _update_page_summary(self) -> None:
        size = cast(int, self.page_size_input.currentData())
        pages = max(1, ceil(self._total / size))
        self.page_label.setText(f"Page {self._page} of {pages} • {self._total} results")
        self.previous_button.setEnabled(not self._busy and self._page > 1)
        self.next_button.setEnabled(not self._busy and self._page < pages)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (
            self.refresh_button,
            self.apply_button,
            self.clear_button,
            self.search_input,
            self.sender_input,
            self.message_input,
            self.status_input,
            self.page_size_input,
        ):
            widget.setEnabled(not busy)
        if busy:
            self.previous_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self.history_button.setEnabled(False)
        else:
            self._update_page_summary()
            self._update_actions()

    def _update_actions(self) -> None:
        self.history_button.setEnabled(not self._busy and self.selected_summary() is not None)

    def _handle_error(self, error: BaseException, context: str) -> None:
        presentation = translate_error(error)
        if presentation.session_invalid:
            self.session_invalidated.emit()
            return
        if presentation.unexpected:
            log_unexpected(self._logger, error, context)
        self.status.show_message(presentation.message)
