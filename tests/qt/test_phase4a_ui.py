"""Headless Phase 4A client, shipment-measurement, and weighing UI tests."""

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
from warehouse_control_center.application.dto import ClientDTO, ShipmentWeightCheckDTO
from warehouse_control_center.domain.enums import UserRole, WeightCheckResult
from warehouse_control_center.presentation.qt.dialogs.client_dialogs import ClientDialog
from warehouse_control_center.presentation.qt.dialogs.shipment_dialogs import (
    ControlWeightDialog,
    NewShipmentDialog,
    ShipmentDetailsDialog,
)
from warehouse_control_center.presentation.qt.pages.clients_page import ClientsPage
from warehouse_control_center.presentation.qt.pages.shipments_page import ShipmentsPage


def _logger() -> logging.Logger:
    logger = logging.getLogger(f"warehouse_control_center.phase4a-ui.{id(object())}")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    return logger


def _client(*, active: bool = True) -> ClientDTO:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return ClientDTO(
        id=7,
        client_code="K-007",
        company_name="Žuti Čempres d.o.o.",
        tax_id=None,
        address="Ulica 1",
        city="Sarajevo",
        contact_name="Amila Hadžić",
        phone="+387 61 111 222",
        email="office@example.test",
        contract_number=None,
        contract_start=None,
        contract_end=None,
        active=active,
        notes=None,
        created_at=now,
        updated_at=now,
    )


class FakeClientService:
    def __init__(self, records: tuple[ClientDTO, ...] = (_client(),)) -> None:
        self.records = list(records)
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.worker_thread_ids: list[int] = []

    def _record(self, name: str, **values: object) -> None:
        self.worker_thread_ids.append(get_ident())
        self.calls.append((name, values))

    def list_clients(self, session: object, **values: object) -> tuple[ClientDTO, ...]:
        del session
        self._record("list_clients", **values)
        return tuple(
            record for record in self.records if not values.get("active_only") or record.active
        )

    def create_client(self, session: object, **values: object) -> ClientDTO:
        del session
        self._record("create_client", **values)
        created = replace(
            _client(),
            id=8,
            client_code=cast(str, values["client_code"]),
            company_name=cast(str, values["company_name"]),
        )
        self.records.append(created)
        return created

    def update_client(self, session: object, client_id: int, **values: object) -> ClientDTO:
        del session
        self._record("update_client", client_id=client_id, **values)
        updated = replace(
            self.records[0],
            company_name=cast(str, values["company_name"]),
        )
        self.records[0] = updated
        return updated

    def activate_client(self, session: object, client_id: int) -> ClientDTO:
        del session
        self._record("activate_client", client_id=client_id)
        self.records[0] = replace(self.records[0], active=True)
        return self.records[0]

    def deactivate_client(self, session: object, client_id: int) -> ClientDTO:
        del session
        self._record("deactivate_client", client_id=client_id)
        self.records[0] = replace(self.records[0], active=False)
        return self.records[0]


class WeightedShipmentService(FakeShipmentService):
    def __init__(self) -> None:
        super().__init__(_shipment())
        self.checks = (
            ShipmentWeightCheckDTO(
                id=1,
                shipment_id=10,
                declared_weight_g_snapshot=1_000,
                measured_weight_g=1_100,
                absolute_difference_g=100,
                difference_percent=None,
                tolerance_abs_g_snapshot=100,
                tolerance_percent_snapshot=None,
                result=WeightCheckResult.UNDER_TOLERANCE,
                checked_by_user_id=2,
                checked_at=datetime(2026, 1, 1, 14, tzinfo=UTC),
                note="Boundary",
            ),
        )

    def get_weight_checks(
        self, session: object, shipment_id: int
    ) -> tuple[ShipmentWeightCheckDTO, ...]:
        del session
        self._call("get_weight_checks", shipment_id)
        return self.checks


@pytest.fixture
def thread_pool() -> QThreadPool:
    pool = QThreadPool()
    pool.setMaxThreadCount(3)
    yield pool
    assert pool.waitForDone(5_000)


def test_clients_page_is_searchable_manageable_and_async(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    gui_thread_id = get_ident()
    service = FakeClientService()
    page = ClientsPage(_session(), cast("Any", service), thread_pool, _logger(), "Europe/Sarajevo")
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: page.table.rowCount() == 1, timeout=3_000)
    assert page.table.item(0, 0).text() == "K-007"
    assert service.worker_thread_ids and all(
        thread_id != gui_thread_id for thread_id in service.worker_thread_ids
    )
    page.search_input.setText("Čempres")
    qtbot.keyPress(page.search_input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: len(service.calls) >= 2, timeout=3_000)
    assert service.calls[-1] == ("list_clients", {"search": "Čempres"})

    qtbot.mouseClick(page.create_button, Qt.MouseButton.LeftButton)
    dialog = cast(ClientDialog, page._dialog)
    dialog.code_input.setText("K-008")
    dialog.company_input.setText("Nova Firma")
    dialog.address_input.setText("Adresa 2")
    dialog.city_input.setText("Mostar")
    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: any(name == "create_client" for name, values in service.calls), timeout=3_000
    )
    qtbot.waitUntil(lambda: not dialog.isVisible(), timeout=3_000)


def test_client_management_actions_are_permission_gated(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    page = ClientsPage(
        _session(UserRole.WAREHOUSE_OPERATOR),
        cast("Any", FakeClientService()),
        thread_pool,
        _logger(),
        "UTC",
    )
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: page.table.rowCount() == 1, timeout=3_000)
    assert not page.create_button.isVisible()
    assert not page.edit_button.isVisible()
    assert not page.activate_button.isVisible()
    assert not page.deactivate_button.isVisible()
    assert page.details_button.isVisible()


def test_new_shipment_uses_searchable_active_client_and_exact_measurements(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    shipments = FakeShipmentService(_shipment())
    clients = FakeClientService((_client(), _client(active=False)))
    page = ShipmentsPage(
        _session(),
        cast("Any", shipments),
        thread_pool,
        _logger(),
        "UTC",
        clients=cast("Any", clients),
    )
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: page.table.rowCount() == 1, timeout=3_000)
    qtbot.mouseClick(page.new_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: page._new_dialog is not None, timeout=3_000)
    dialog = cast(NewShipmentDialog, page._new_dialog)
    assert dialog.client_input.isEditable()
    assert dialog.client_input.count() == 2
    dialog.client_input.setCurrentIndex(1)
    assert dialog.sender_input.text() == _client().company_name
    assert dialog.sender_input.isReadOnly()
    dialog.recipient_input.setText("Recipient")
    dialog.phone_input.setText("123")
    dialog.address_input.setText("Address")
    dialog.city_input.setText("City")
    dialog.package_count_input.setValue(3)
    dialog.length_input.setText("10.2")
    dialog.width_input.setText("20")
    dialog.height_input.setText("30")
    dialog.declared_weight_input.setText("10.250")
    qtbot.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: any(call[0] == "create_shipment" for call in shipments.calls), timeout=3_000
    )
    call = next(call for call in shipments.calls if call[0] == "create_shipment")
    assert call[2]["sender_client_id"] == 7
    assert call[2]["package_count"] == 3
    assert call[2]["length_cm"] == "10.2"
    assert call[2]["declared_weight_g"] == 10_250


def test_control_weight_and_history_are_async_and_permission_aware(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    gui_thread_id = get_ident()
    service = WeightedShipmentService()
    page = ShipmentsPage(
        _session(UserRole.WAREHOUSE_OPERATOR),
        cast("Any", service),
        thread_pool,
        _logger(),
        "UTC",
    )
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: page.table.rowCount() == 1, timeout=3_000)
    page.table.selectRow(0)
    assert page.control_weight_button.isVisible()
    assert page.control_weight_button.isEnabled()
    qtbot.mouseClick(page.control_weight_button, Qt.MouseButton.LeftButton)
    dialog = cast(ControlWeightDialog, page._control_weight_dialog)
    dialog.measured_input.setText("1.100")
    dialog.note_input.setPlainText("Second check")
    qtbot.mouseClick(dialog.record_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: any(call[0] == "record_control_weight" for call in service.calls), timeout=3_000
    )
    call = next(call for call in service.calls if call[0] == "record_control_weight")
    assert call[2] == {"measured_weight_g": 1_100, "note": "Second check"}
    assert all(thread_id != gui_thread_id for thread_id in service.worker_thread_ids)

    page.table.selectRow(0)
    qtbot.mouseClick(page.details_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: page._details_dialog is not None, timeout=3_000)
    details = cast(ShipmentDetailsDialog, page._details_dialog)
    history = details.findChild(QTableWidget, "shipmentWeightHistoryTable")
    assert history is not None and history.rowCount() == 1
    assert history.item(0, 5).text() == "Under Tolerance"
    assert history.item(0, 6).text() == "2"
    assert history.item(0, 7).text() == "Boundary"


def test_control_weight_is_disabled_without_declared_weight(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    service = FakeShipmentService(replace(_shipment(), declared_weight_g=None))
    page = ShipmentsPage(_session(), cast("Any", service), thread_pool, _logger(), "UTC")
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: page.table.rowCount() == 1, timeout=3_000)
    page.table.selectRow(0)
    assert not page.control_weight_button.isEnabled()
