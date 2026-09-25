"""Headless Phase 4C shipment SMS UI and worker tests."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from threading import get_ident
from typing import Any, cast

import pytest
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QTableWidget
from pytestqt.qtbot import QtBot

from tests.qt.test_shipments_ui import FakeShipmentService, _session, _shipment
from warehouse_control_center.application.dto import (
    ShipmentSmsEventDTO,
    ShipmentSmsEventPage,
    ShipmentSmsSummaryDTO,
    ShipmentSmsSummaryPage,
)
from warehouse_control_center.domain.enums import (
    SmsMessageType,
    SmsSenderType,
    SmsSendStatus,
)
from warehouse_control_center.presentation.qt.dialogs.shipment_dialogs import (
    ShipmentDetailsDialog,
)
from warehouse_control_center.presentation.qt.dialogs.sms_dialogs import (
    RecordSmsDialog,
    ShipmentSmsHistoryDialog,
)
from warehouse_control_center.presentation.qt.pages.shipments_page import ShipmentsPage
from warehouse_control_center.presentation.qt.pages.sms_shipments_page import SmsShipmentsPage


def _logger() -> logging.Logger:
    logger = logging.getLogger(f"warehouse_control_center.phase4c-ui.{id(object())}")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    return logger


def _event(
    event_id: int = 1,
    *,
    sender_type: SmsSenderType = SmsSenderType.WAREHOUSE,
    message_type: SmsMessageType = SmsMessageType.CUSTOM,
    message_text: str = "Recorded SMS",
) -> ShipmentSmsEventDTO:
    timestamp = datetime(2026, 1, 1, 15, tzinfo=UTC)
    return ShipmentSmsEventDTO(
        id=event_id,
        shipment_id=10,
        sender_type=sender_type,
        sent_by_user_id=1 if sender_type is not SmsSenderType.SYSTEM else None,
        phone_number="+387 65 123 456",
        message_type=message_type,
        message_text=message_text,
        send_status=SmsSendStatus.RECORDED,
        sent_at=timestamp,
        delivered_at=None,
        provider_message_id=None,
        error_message=None,
        created_at=timestamp,
    )


class FakeSmsService:
    def __init__(self, events: tuple[ShipmentSmsEventDTO, ...] = ()) -> None:
        self.events = list(events)
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.worker_thread_ids: list[int] = []

    def _call(self, name: str, **kwargs: object) -> None:
        self.worker_thread_ids.append(get_ident())
        self.calls.append((name, kwargs))

    def record_sms(self, session: object, shipment_id: int, **kwargs: Any) -> ShipmentSmsEventDTO:
        del session
        self._call("record_sms", shipment_id=shipment_id, **kwargs)
        event = replace(
            _event(len(self.events) + 1),
            sender_type=cast(SmsSenderType, kwargs["sender_type"]),
            message_type=cast(SmsMessageType, kwargs["message_type"]),
            message_text=cast(str | None, kwargs["message_text"]) or "Template message",
            phone_number=cast(str, kwargs["phone_number"]),
        )
        self.events.append(event)
        return event

    def list_sms_for_shipment(
        self, session: object, shipment_id: int, **kwargs: Any
    ) -> ShipmentSmsEventPage:
        del session
        self._call("list_sms_for_shipment", shipment_id=shipment_id, **kwargs)
        items = tuple(reversed(self.events))
        return ShipmentSmsEventPage(items, 1, cast(int, kwargs.get("page_size", 50)), len(items))

    def list_shipments_with_sms(self, session: object, **kwargs: Any) -> ShipmentSmsSummaryPage:
        del session
        self._call("list_shipments_with_sms", **kwargs)
        if not self.events:
            return ShipmentSmsSummaryPage((), 1, cast(int, kwargs["page_size"]), 0)
        summary = ShipmentSmsSummaryDTO(_shipment(), len(self.events), self.events[-1])
        return ShipmentSmsSummaryPage(
            (summary,), cast(int, kwargs["page"]), cast(int, kwargs["page_size"]), 1
        )


@pytest.fixture
def thread_pool() -> QThreadPool:
    pool = QThreadPool()
    pool.setMaxThreadCount(3)
    yield pool
    assert pool.waitForDone(5_000)


def test_record_dialog_defaults_and_custom_validation(qtbot: QtBot) -> None:
    dialog = RecordSmsDialog(_shipment())
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.phone_input.text() == _shipment().recipient_phone
    assert dialog.sender_input.currentData() == SmsSenderType.WAREHOUSE.value
    assert dialog.status_input.currentData() == SmsSendStatus.RECORDED.value
    dialog.message_type_input.setCurrentIndex(
        dialog.message_type_input.findData(SmsMessageType.CUSTOM.value)
    )
    qtbot.mouseClick(dialog.record_button, Qt.MouseButton.LeftButton)
    assert "required" in dialog.status.message.casefold()


def test_shipment_record_and_details_history_are_async(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    gui_thread_id = get_ident()
    shipments = FakeShipmentService(_shipment())
    sms = FakeSmsService()
    page = ShipmentsPage(
        _session(),
        cast("Any", shipments),
        thread_pool,
        _logger(),
        "UTC",
        shipment_sms=cast("Any", sms),
    )
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: page.table.rowCount() == 1, timeout=3_000)
    page.table.selectRow(0)
    assert page.record_sms_button.isVisible() and page.record_sms_button.isEnabled()
    qtbot.mouseClick(page.record_sms_button, Qt.MouseButton.LeftButton)
    dialog = cast(RecordSmsDialog, page._sms_dialog)
    dialog.message_type_input.setCurrentIndex(
        dialog.message_type_input.findData(SmsMessageType.CUSTOM.value)
    )
    dialog.message_input.setPlainText("Unicode poruka — Željko")
    qtbot.mouseClick(dialog.record_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: any(call[0] == "record_sms" for call in sms.calls), timeout=3_000)
    qtbot.waitUntil(lambda: not dialog.isVisible(), timeout=3_000)
    record_call = next(call for call in sms.calls if call[0] == "record_sms")
    assert record_call[1]["message_text"] == "Unicode poruka — Željko"
    assert sms.worker_thread_ids[-1] != gui_thread_id

    qtbot.waitUntil(lambda: page.refresh_button.isEnabled(), timeout=3_000)
    page.table.selectRow(0)
    qtbot.mouseClick(page.details_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: page._details_dialog is not None, timeout=3_000)
    details = cast(ShipmentDetailsDialog, page._details_dialog)
    history = details.findChild(QTableWidget, "shipmentSmsHistoryTable")
    assert history is not None and history.rowCount() == 1
    assert history.item(0, 6).text() == "Unicode poruka — Željko"


def test_archived_shipment_disables_record_action(qtbot: QtBot, thread_pool: QThreadPool) -> None:
    page = ShipmentsPage(
        _session(),
        cast("Any", FakeShipmentService(_shipment(archived=True))),
        thread_pool,
        _logger(),
        "UTC",
        shipment_sms=cast("Any", FakeSmsService()),
    )
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: page.table.rowCount() == 1, timeout=3_000)
    page.table.selectRow(0)
    assert not page.record_sms_button.isEnabled()


def test_sms_shipments_page_filters_paginates_and_opens_history_off_gui_thread(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    gui_thread_id = get_ident()
    sms = FakeSmsService(
        (
            _event(),
            _event(
                2,
                sender_type=SmsSenderType.COURIER,
                message_type=SmsMessageType.DELIVERY_ATTEMPT,
                message_text="Second",
            ),
        )
    )
    page = SmsShipmentsPage(_session(), cast("Any", sms), thread_pool, _logger(), "UTC")
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: page.table.rowCount() == 1, timeout=3_000)
    assert page.table.item(0, 0).text() == _shipment().shipment_number
    assert page.table.item(0, 4).text() == "2"
    assert page.table.item(0, 6).text() == "Courier"
    page.search_input.setText("E000000")
    page.sender_input.setCurrentIndex(page.sender_input.findData(SmsSenderType.COURIER.value))
    qtbot.mouseClick(page.apply_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: len([call for call in sms.calls if call[0] == "list_shipments_with_sms"]) >= 2,
        timeout=3_000,
    )
    assert sms.calls[-1][1]["search"] == "E000000"
    assert sms.calls[-1][1]["sender_type"] is SmsSenderType.COURIER

    qtbot.waitUntil(lambda: page.refresh_button.isEnabled(), timeout=3_000)
    page.table.selectRow(0)
    qtbot.mouseClick(page.history_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: page._history_dialog is not None, timeout=3_000)
    history_dialog = cast(ShipmentSmsHistoryDialog, page._history_dialog)
    history = history_dialog.findChild(QTableWidget, "shipmentSmsHistoryTable")
    assert history is not None and history.rowCount() == 2
    assert all(thread_id != gui_thread_id for thread_id in sms.worker_thread_ids)
