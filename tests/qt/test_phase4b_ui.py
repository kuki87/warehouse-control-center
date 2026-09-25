"""Headless Phase 4B payment and additional-service UI tests."""

from __future__ import annotations

import logging
from dataclasses import replace
from threading import get_ident
from typing import Any, cast

import pytest
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QLabel, QTabWidget
from pytestqt.qtbot import QtBot

from tests.qt.test_shipments_ui import FakeShipmentService, _session, _shipment
from warehouse_control_center.domain.enums import (
    AdditionalServiceType,
    PaymentMethod,
    ShipmentPayer,
)
from warehouse_control_center.presentation.qt.dialogs.shipment_dialogs import (
    EditShipmentDialog,
    NewShipmentDialog,
    ShipmentDetailsData,
    ShipmentDetailsDialog,
)
from warehouse_control_center.presentation.qt.pages.shipments_page import ShipmentsPage


def _logger() -> logging.Logger:
    logger = logging.getLogger(f"warehouse_control_center.phase4b-ui.{id(object())}")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    return logger


@pytest.fixture
def thread_pool() -> QThreadPool:
    pool = QThreadPool()
    pool.setMaxThreadCount(3)
    yield pool
    assert pool.waitForDone(5_000)


def _page(qtbot: QtBot, thread_pool: QThreadPool, service: FakeShipmentService) -> ShipmentsPage:
    page = ShipmentsPage(
        _session(), cast("Any", service), thread_pool, _logger(), "Europe/Sarajevo"
    )
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: bool(service.list_calls), timeout=3_000)
    qtbot.waitUntil(lambda: page.refresh_button.isEnabled(), timeout=3_000)
    return page


def _complete_required_fields(dialog: NewShipmentDialog) -> None:
    dialog.sender_input.setText("Sender")
    dialog.recipient_input.setText("Recipient")
    dialog.phone_input.setText("+387 61 111 222")
    dialog.address_input.setText("Address 1")
    dialog.city_input.setText("Sarajevo")


def test_create_payment_services_uses_exact_fenings_and_worker(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    gui_thread_id = get_ident()
    service = FakeShipmentService(_shipment())
    page = _page(qtbot, thread_pool, service)
    qtbot.mouseClick(page.new_button, Qt.MouseButton.LeftButton)
    dialog = cast(NewShipmentDialog, page._new_dialog)
    _complete_required_fields(dialog)
    payment = dialog.payment_fields
    assert not payment.cod_amount_input.isEnabled()
    payment.declared_value_input.setText("123.45")
    payment.cod_enabled_input.setChecked(True)
    assert payment.cod_amount_input.isEnabled()
    payment.cod_amount_input.setText("67.89")
    payment.payer_input.setCurrentIndex(payment.payer_input.findData(ShipmentPayer.RECIPIENT.value))
    payment.payment_method_input.setCurrentIndex(
        payment.payment_method_input.findData(PaymentMethod.CASH.value)
    )
    payment.service_inputs[AdditionalServiceType.EXPRESS].setChecked(True)
    payment.service_inputs[AdditionalServiceType.INSURANCE].setChecked(True)

    qtbot.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: any(call[0] == "create_shipment" for call in service.calls),
        timeout=3_000,
    )
    call = next(call for call in service.calls if call[0] == "create_shipment")
    assert call[2]["declared_value_fen"] == 12_345
    assert call[2]["cod_enabled"] is True
    assert call[2]["cod_amount_fen"] == 6_789
    assert call[2]["payer"] is ShipmentPayer.RECIPIENT
    assert call[2]["payment_method"] is PaymentMethod.CASH
    assert call[2]["services"] == (
        AdditionalServiceType.EXPRESS,
        AdditionalServiceType.INSURANCE,
    )
    assert service.worker_thread_ids[-1] != gui_thread_id


def test_payment_validation_is_actionable_and_blocks_submission(qtbot: QtBot) -> None:
    dialog = NewShipmentDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    _complete_required_fields(dialog)
    payment = dialog.payment_fields
    payment.declared_value_input.setText("1.001")
    qtbot.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
    assert "two decimal places" in dialog.status.message

    payment.declared_value_input.clear()
    payment.service_inputs[AdditionalServiceType.INSURANCE].setChecked(True)
    qtbot.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
    assert "Insurance requires a declared value" in dialog.status.message

    payment.service_inputs[AdditionalServiceType.INSURANCE].setChecked(False)
    payment.cod_enabled_input.setChecked(True)
    qtbot.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
    assert "COD amount is required" in dialog.status.message


def test_edit_populates_and_can_clear_cod_and_replace_services(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    shipment = replace(
        _shipment(version=4),
        declared_value_fen=10_005,
        cod_enabled=True,
        cod_amount_fen=5_050,
        payer=ShipmentPayer.SENDER,
        payment_method=PaymentMethod.ACCOUNT,
        services=(AdditionalServiceType.EXPRESS, AdditionalServiceType.INSURANCE),
    )
    service = FakeShipmentService(shipment)
    page = _page(qtbot, thread_pool, service)
    page.table.selectRow(0)
    qtbot.mouseClick(page.edit_button, Qt.MouseButton.LeftButton)
    dialog = cast(EditShipmentDialog, page._edit_dialog)
    payment = dialog.payment_fields
    assert payment.declared_value_input.text() == "100.05"
    assert payment.cod_amount_input.text() == "50.50"
    assert payment.cod_enabled_input.isChecked()
    assert payment.service_inputs[AdditionalServiceType.INSURANCE].isChecked()

    payment.cod_enabled_input.setChecked(False)
    assert not payment.cod_amount_input.isEnabled()
    assert payment.cod_amount_input.text() == ""
    payment.service_inputs[AdditionalServiceType.EXPRESS].setChecked(False)
    payment.service_inputs[AdditionalServiceType.INSURANCE].setChecked(False)
    payment.service_inputs[AdditionalServiceType.SATURDAY_DELIVERY].setChecked(True)
    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: any(call[0] == "update_shipment" for call in service.calls),
        timeout=3_000,
    )
    call = next(call for call in service.calls if call[0] == "update_shipment")
    assert call[2]["expected_version"] == 4
    assert call[2]["cod_enabled"] is False
    assert call[2]["cod_amount_fen"] is None
    assert call[2]["services"] == (AdditionalServiceType.SATURDAY_DELIVERY,)


def test_details_show_structured_payment_and_omit_empty_section(qtbot: QtBot) -> None:
    shipment = replace(
        _shipment(),
        declared_value_fen=12_345,
        cod_enabled=True,
        cod_amount_fen=6_789,
        payer=ShipmentPayer.RECIPIENT,
        payment_method=PaymentMethod.INVOICE,
        services=(
            AdditionalServiceType.EXPRESS,
            AdditionalServiceType.RETURN_DOCUMENTS,
        ),
    )
    dialog = ShipmentDetailsDialog(ShipmentDetailsData(shipment, (), None), "UTC")
    qtbot.addWidget(dialog)
    tabs = dialog.findChild(QTabWidget, "shipmentDetailsTabs")
    assert tabs is not None
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        "Details",
        "Payment & Services",
        "History",
        "Problem",
        "Weight history",
    ]
    labels = {label.text() for label in dialog.findChildren(QLabel)}
    assert "123.45 BAM" in labels
    assert "67.89 BAM" in labels
    assert "Recipient" in labels
    assert "Invoice" in labels
    assert "Express, Return Documents" in labels

    empty = ShipmentDetailsDialog(ShipmentDetailsData(_shipment(), (), None), "UTC")
    qtbot.addWidget(empty)
    empty_tabs = empty.findChild(QTabWidget, "shipmentDetailsTabs")
    assert empty_tabs is not None
    assert "Payment & Services" not in [
        empty_tabs.tabText(index) for index in range(empty_tabs.count())
    ]
