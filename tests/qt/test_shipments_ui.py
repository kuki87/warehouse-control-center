"""Headless tests for the Phase 3B shipment desktop workflow."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from threading import get_ident
from typing import Any, cast

import pytest
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton
from pytestqt.qtbot import QtBot

from warehouse_control_center.application.dto import (
    SessionContext,
    ShipmentDTO,
    ShipmentPage,
    ShipmentProblemDTO,
    ShipmentStatusChangeResult,
    ShipmentStatusHistoryDTO,
)
from warehouse_control_center.domain.enums import (
    AdditionalServiceType,
    PaymentMethod,
    ProblemType,
    ShipmentPayer,
    ShipmentStatus,
    UserRole,
)
from warehouse_control_center.domain.exceptions import (
    InvalidShipmentError,
    InvalidShipmentTransitionError,
    PermissionDeniedError,
    ShipmentArchivedError,
    ShipmentConflictError,
    ShipmentNumberAllocationError,
    ShipmentNumberExhaustedError,
    ShipmentProblemOpenError,
)
from warehouse_control_center.presentation.qt.dialogs.confirm_dialog import ConfirmDialog
from warehouse_control_center.presentation.qt.dialogs.shipment_dialogs import (
    ChangeStatusDialog,
    EditShipmentDialog,
    NewShipmentDialog,
    ReportProblemDialog,
    ResolveProblemDialog,
    ShipmentDetailsDialog,
)
from warehouse_control_center.presentation.qt.pages.shipments_page import ShipmentsPage
from warehouse_control_center.presentation.qt.windows.main_window import MainWindow


def _session(role: UserRole = UserRole.ADMIN) -> SessionContext:
    return SessionContext(1, "admin", role, datetime(2026, 1, 1, tzinfo=UTC))


def _shipment(
    *,
    status: ShipmentStatus = ShipmentStatus.RECEIVED,
    archived: bool = False,
    version: int = 1,
) -> ShipmentDTO:
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    return ShipmentDTO(
        id=10,
        shipment_number="SHP-000010",
        recipient_name="Željko Šarić",
        recipient_address="Ćirila i Metodija 10",
        recipient_city="Banja Luka",
        recipient_phone="+387 65 123 456",
        sender_name="Đorđe Čavić",
        sender_client_id=None,
        package_count=1,
        length_cm=None,
        width_cm=None,
        height_cm=None,
        declared_weight_g=1_000,
        courier_id=None,
        status=status,
        received_at=now,
        sorted_at=None,
        assigned_at=None,
        dispatched_at=None,
        created_at=now,
        updated_at=now,
        created_by=1,
        notes="Handle carefully",
        archived_at=now if archived else None,
        version=version,
    )


def _problem() -> ShipmentProblemDTO:
    return ShipmentProblemDTO(
        id=50,
        shipment_id=10,
        problem_type=ProblemType.DAMAGED,
        description="Damaged corner",
        previous_status=ShipmentStatus.SORTING,
        reported_by=1,
        reported_at=datetime(2026, 1, 1, 13, tzinfo=UTC),
        resolved_by=None,
        resolved_at=None,
    )


def _logger() -> logging.Logger:
    logger = logging.getLogger(f"warehouse_control_center.shipment-ui.{id(object())}")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    return logger


class FakeShipmentService:
    def __init__(self, record: ShipmentDTO | None = None) -> None:
        self.records = [] if record is None else [record]
        self.list_calls: list[dict[str, Any]] = []
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.failures: dict[str, BaseException] = {}
        self.worker_thread_ids: list[int] = []
        self.problem: ShipmentProblemDTO | None = (
            _problem() if record is not None and record.status is ShipmentStatus.PROBLEM else None
        )

    def _call(self, name: str, *args: object, **kwargs: object) -> None:
        self.worker_thread_ids.append(get_ident())
        self.calls.append((name, args, kwargs))
        error = self.failures.pop(name, None)
        if error is not None:
            raise error

    def list_shipments(self, session: SessionContext, **kwargs: Any) -> ShipmentPage:
        del session
        self._call("list_shipments", **kwargs)
        self.list_calls.append(dict(kwargs))
        page = cast(int, kwargs["page"])
        size = cast(int, kwargs["page_size"])
        return ShipmentPage(tuple(self.records), page, size, len(self.records))

    def create_shipment(self, session: SessionContext, **kwargs: Any) -> ShipmentDTO:
        del session
        self._call("create_shipment", **kwargs)
        created = replace(
            _shipment(),
            shipment_number="E000000123",
            sender_name=cast(str, kwargs["sender_name"]),
            recipient_name=cast(str, kwargs["recipient_name"]),
            recipient_address=cast(str, kwargs["recipient_address"]),
            recipient_city=cast(str, kwargs["recipient_city"]),
            recipient_phone=cast(str, kwargs["recipient_phone"]),
            declared_value_fen=cast(int | None, kwargs.get("declared_value_fen")),
            cod_enabled=cast(bool, kwargs.get("cod_enabled", False)),
            cod_amount_fen=cast(int | None, kwargs.get("cod_amount_fen")),
            payer=cast(ShipmentPayer | None, kwargs.get("payer")),
            payment_method=cast(PaymentMethod | None, kwargs.get("payment_method")),
            services=cast(tuple[AdditionalServiceType, ...], kwargs.get("services", ())),
        )
        self.records = [created]
        return created

    def update_shipment(
        self, session: SessionContext, shipment_id: int, **kwargs: Any
    ) -> ShipmentDTO:
        del session
        self._call("update_shipment", shipment_id, **kwargs)
        record = self.records[0]
        updated = replace(
            record,
            recipient_name=cast(str, kwargs["recipient_name"]),
            recipient_address=cast(str, kwargs["recipient_address"]),
            recipient_city=cast(str, kwargs["recipient_city"]),
            recipient_phone=cast(str, kwargs["recipient_phone"]),
            sender_name=cast(str, kwargs["sender_name"]),
            notes=cast(str | None, kwargs["notes"]),
            declared_value_fen=cast(
                int | None, kwargs.get("declared_value_fen", record.declared_value_fen)
            ),
            cod_enabled=cast(bool, kwargs.get("cod_enabled", record.cod_enabled)),
            cod_amount_fen=cast(int | None, kwargs.get("cod_amount_fen", record.cod_amount_fen)),
            payer=cast(ShipmentPayer | None, kwargs.get("payer", record.payer)),
            payment_method=cast(
                PaymentMethod | None,
                kwargs.get("payment_method", record.payment_method),
            ),
            services=cast(
                tuple[AdditionalServiceType, ...],
                kwargs.get("services", record.services),
            ),
            version=record.version + 1,
        )
        self.records = [updated]
        return updated

    def get_shipment(self, session: SessionContext, shipment_id: int) -> ShipmentDTO:
        del session
        self._call("get_shipment", shipment_id)
        return self.records[0]

    def get_status_history(
        self, session: SessionContext, shipment_id: int
    ) -> tuple[ShipmentStatusHistoryDTO, ...]:
        del session
        self._call("get_status_history", shipment_id)
        return (
            ShipmentStatusHistoryDTO(
                id=1,
                shipment_id=shipment_id,
                old_status=ShipmentStatus.RECEIVED,
                new_status=ShipmentStatus.SORTING,
                changed_by=1,
                timestamp=datetime(2026, 1, 1, 13, tzinfo=UTC),
                reason="Sorted",
                is_admin_override=False,
            ),
        )

    def get_open_problem(
        self, session: SessionContext, shipment_id: int
    ) -> ShipmentProblemDTO | None:
        del session
        self._call("get_open_problem", shipment_id)
        return self.problem

    def get_weight_checks(self, session: SessionContext, shipment_id: int) -> tuple[()]:
        del session
        self._call("get_weight_checks", shipment_id)
        return ()

    def record_control_weight(
        self, session: SessionContext, shipment_id: int, **kwargs: Any
    ) -> object:
        del session
        self._call("record_control_weight", shipment_id, **kwargs)
        return object()

    def change_status(
        self,
        session: SessionContext,
        shipment_id: int,
        target_status: ShipmentStatus,
        **kwargs: Any,
    ) -> ShipmentStatusChangeResult:
        del session
        self._call("change_status", shipment_id, target_status, **kwargs)
        changed = replace(
            self.records[0], status=target_status, version=self.records[0].version + 1
        )
        self.records = [changed]
        return ShipmentStatusChangeResult(changed, True)

    def report_problem(
        self,
        session: SessionContext,
        shipment_id: int,
        problem_type: ProblemType,
        **kwargs: Any,
    ) -> ShipmentProblemDTO:
        del session
        self._call("report_problem", shipment_id, problem_type, **kwargs)
        self.problem = replace(_problem(), problem_type=problem_type)
        self.records = [
            replace(
                self.records[0],
                status=ShipmentStatus.PROBLEM,
                version=self.records[0].version + 1,
            )
        ]
        return self.problem

    def resolve_problem(
        self, session: SessionContext, shipment_id: int, **kwargs: Any
    ) -> ShipmentProblemDTO:
        del session
        self._call("resolve_problem", shipment_id, **kwargs)
        assert self.problem is not None
        resolved = replace(
            self.problem,
            resolved_by=1,
            resolved_at=datetime(2026, 1, 1, 14, tzinfo=UTC),
        )
        self.problem = None
        self.records = [
            replace(
                self.records[0],
                status=cast(ShipmentStatus, kwargs["recovery_status"]),
                version=self.records[0].version + 1,
            )
        ]
        return resolved

    def archive_shipment(
        self, session: SessionContext, shipment_id: int, **kwargs: Any
    ) -> ShipmentDTO:
        del session
        self._call("archive_shipment", shipment_id, **kwargs)
        archived = replace(
            self.records[0],
            archived_at=datetime(2026, 1, 1, 14, tzinfo=UTC),
            version=self.records[0].version + 1,
        )
        self.records = [archived]
        return archived

    def restore_shipment(
        self, session: SessionContext, shipment_id: int, **kwargs: Any
    ) -> ShipmentDTO:
        del session
        self._call("restore_shipment", shipment_id, **kwargs)
        restored = replace(self.records[0], archived_at=None, version=self.records[0].version + 1)
        self.records = [restored]
        return restored


@pytest.fixture
def thread_pool() -> QThreadPool:
    pool = QThreadPool()
    pool.setMaxThreadCount(3)
    yield pool
    assert pool.waitForDone(5_000)


def _page(
    qtbot: QtBot,
    thread_pool: QThreadPool,
    service: FakeShipmentService,
    role: UserRole = UserRole.ADMIN,
) -> ShipmentsPage:
    page = ShipmentsPage(
        _session(role), cast("Any", service), thread_pool, _logger(), "Europe/Sarajevo"
    )
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: bool(service.list_calls), timeout=3_000)
    qtbot.waitUntil(lambda: page.refresh_button.isEnabled(), timeout=3_000)
    return page


def test_page_loads_data_filters_paginates_and_runs_off_gui_thread(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    gui_thread_id = get_ident()
    service = FakeShipmentService(_shipment())
    page = _page(qtbot, thread_pool, service)
    assert page.table.rowCount() == 1
    assert page.table.item(0, 0).text() == "SHP-000010"
    headers = [
        page.table.horizontalHeaderItem(index).text() for index in range(page.table.columnCount())
    ]
    assert headers[0] == "Shipment Number"
    assert "Tracking Number" not in headers
    assert "Barcode" not in headers
    assert page.search_input.placeholderText().startswith("Shipment number")
    assert "CET" in page.table.item(0, 11).text()
    assert all(thread_id != gui_thread_id for thread_id in service.worker_thread_ids)

    page.search_input.setText("Željko")
    page.city_input.setText("Banja Luka")
    page.status_input.setCurrentIndex(page.status_input.findData(ShipmentStatus.RECEIVED.value))
    page.courier_input.setValue(7)
    page.problem_only_input.setChecked(True)
    page.include_archived_input.setChecked(True)
    qtbot.mouseClick(page.apply_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: len(service.list_calls) >= 2, timeout=3_000)
    qtbot.waitUntil(lambda: page.refresh_button.isEnabled(), timeout=3_000)
    call = service.list_calls[-1]
    assert call["search"] == "Željko"
    assert call["city"] == "Banja Luka"
    assert call["status"] is ShipmentStatus.RECEIVED
    assert call["courier_id"] == 7
    assert call["problem_only"] is True
    assert call["include_archived"] is True

    page._total = 60
    page._update_page_summary()
    assert page.next_button.isEnabled()
    page.next_page()
    qtbot.waitUntil(lambda: any(call["page"] == 2 for call in service.list_calls), timeout=3_000)


def test_main_window_replaces_shipments_placeholder(qtbot: QtBot, thread_pool: QThreadPool) -> None:
    service = FakeShipmentService(_shipment())
    window = MainWindow(
        _session(UserRole.WAREHOUSE_OPERATOR),
        cast("Any", object()),
        thread_pool,
        _logger(),
        shipments=cast("Any", service),
        timezone_name="Europe/Sarajevo",
    )
    qtbot.addWidget(window)
    assert isinstance(window.page("shipments"), ShipmentsPage)
    qtbot.waitUntil(lambda: bool(service.list_calls), timeout=3_000)


def test_stale_load_response_cannot_replace_newer_results(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    service = FakeShipmentService(_shipment())
    page = _page(qtbot, thread_pool, service)
    current_generation = page._load_generation
    newer = replace(_shipment(), shipment_number="NEWEST")
    older = replace(_shipment(), shipment_number="STALE")
    page._populate(
        current_generation,
        None,
        ShipmentPage((newer,), 1, 50, 1),
    )
    page._populate(
        current_generation - 1,
        None,
        ShipmentPage((older,), 1, 50, 1),
    )
    assert page.table.item(0, 0).text() == "NEWEST"


def test_empty_and_service_error_states_recover(qtbot: QtBot, thread_pool: QThreadPool) -> None:
    service = FakeShipmentService()
    page = _page(qtbot, thread_pool, service)
    assert page.status.message == "No shipments found."
    service.failures["list_shipments"] = RuntimeError("database internals")
    qtbot.mouseClick(page.refresh_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: page.status.message == "An unexpected error occurred.", timeout=3_000)
    assert "database internals" not in page.status.message
    assert page.refresh_button.isEnabled()


def test_stale_session_error_invalidates_desktop_session(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    service = FakeShipmentService(_shipment())
    page = _page(qtbot, thread_pool, service)
    service.failures["list_shipments"] = PermissionDeniedError(
        "Current session is no longer authorized"
    )
    with qtbot.waitSignal(page.session_invalidated, timeout=3_000):
        qtbot.mouseClick(page.refresh_button, Qt.MouseButton.LeftButton)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (ShipmentNumberExhaustedError("raw"), "capacity is exhausted"),
        (ShipmentNumberAllocationError("raw"), "allocated safely"),
        (InvalidShipmentError("Phone is invalid"), "Phone is invalid"),
    ],
)
def test_new_shipment_validation_submission_and_errors(
    qtbot: QtBot,
    thread_pool: QThreadPool,
    error: BaseException,
    message: str,
) -> None:
    service = FakeShipmentService(_shipment())
    page = _page(qtbot, thread_pool, service)
    qtbot.mouseClick(page.new_button, Qt.MouseButton.LeftButton)
    dialog = cast(NewShipmentDialog, page._new_dialog)
    assert dialog.findChild(QLineEdit, "shipmentTracking") is None
    assert dialog.findChild(QLineEdit, "shipmentBarcode") is None
    qtbot.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
    assert "required" in dialog.status.message
    dialog.sender_input.setText("Pošiljalac")
    dialog.recipient_input.setText("Primalac")
    dialog.phone_input.setText("+387 65 111 222")
    dialog.address_input.setText("Adresa 1")
    dialog.city_input.setText("Sarajevo")
    service.failures["create_shipment"] = error
    qtbot.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(dialog.status.message), timeout=3_000)
    assert message.casefold() in dialog.status.message.casefold()
    assert dialog.create_button.isEnabled()


def test_create_and_edit_success_use_supported_fields_and_expected_version(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    service = FakeShipmentService(_shipment())
    page = _page(qtbot, thread_pool, service)
    qtbot.mouseClick(page.new_button, Qt.MouseButton.LeftButton)
    create = cast(NewShipmentDialog, page._new_dialog)
    for field, value in (
        (create.sender_input, "Pošiljalac"),
        (create.recipient_input, "Primalac"),
        (create.phone_input, "+387 65 111 222"),
        (create.address_input, "Adresa 1"),
        (create.city_input, "Sarajevo"),
    ):
        field.setText(value)
    qtbot.mouseClick(create.create_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not create.isVisible(), timeout=3_000)
    qtbot.waitUntil(lambda: page.table.item(0, 0).text() == "E000000123", timeout=3_000)
    assert "E000000123" in page.status.message
    create_call = next(call for call in service.calls if call[0] == "create_shipment")
    assert "shipment_number" not in create_call[2]
    assert "barcode" not in create_call[2]

    page.table.selectRow(0)
    qtbot.mouseClick(page.edit_button, Qt.MouseButton.LeftButton)
    edit = cast(EditShipmentDialog, page._edit_dialog)
    assert edit.recipient_input.text() == "Primalac"
    edit.recipient_input.setText("Novo ime")
    qtbot.mouseClick(edit.save_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not edit.isVisible(), timeout=3_000)
    update = next(call for call in service.calls if call[0] == "update_shipment")
    assert update[2]["expected_version"] == 1
    assert update[2]["recipient_name"] == "Novo ime"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ShipmentConflictError("raw"), "changed by another operation"),
        (ShipmentArchivedError("raw"), "Archived shipments cannot be changed"),
    ],
)
def test_edit_conflict_and_archived_rejection_are_actionable(
    qtbot: QtBot,
    thread_pool: QThreadPool,
    error: BaseException,
    expected: str,
) -> None:
    service = FakeShipmentService(_shipment())
    page = _page(qtbot, thread_pool, service)
    page.table.selectRow(0)
    qtbot.mouseClick(page.edit_button, Qt.MouseButton.LeftButton)
    dialog = cast(EditShipmentDialog, page._edit_dialog)
    service.failures["update_shipment"] = error
    qtbot.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(dialog.status.message), timeout=3_000)
    assert expected.casefold() in dialog.status.message.casefold()
    assert dialog.isVisible()


def test_status_workflow_override_and_rejection(qtbot: QtBot, thread_pool: QThreadPool) -> None:
    service = FakeShipmentService(_shipment())
    page = _page(qtbot, thread_pool, service)
    page.table.selectRow(0)
    qtbot.mouseClick(page.change_status_button, Qt.MouseButton.LeftButton)
    dialog = cast(ChangeStatusDialog, page._status_dialog)
    targets = {dialog.target_input.itemData(index) for index in range(dialog.target_input.count())}
    assert targets == {ShipmentStatus.SORTING.value}
    assert dialog.override_input.isVisible()
    dialog.override_input.setChecked(True)
    dialog.target_input.setCurrentIndex(
        dialog.target_input.findData(ShipmentStatus.DISPATCHED.value)
    )
    qtbot.mouseClick(dialog.change_button, Qt.MouseButton.LeftButton)
    assert "reason" in dialog.status.message.casefold()
    dialog.reason_input.setPlainText("Operational correction")
    service.failures["change_status"] = InvalidShipmentTransitionError("Rejected transition")
    qtbot.mouseClick(dialog.change_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "Rejected" in dialog.status.message, timeout=3_000)


def test_status_success_details_and_history(qtbot: QtBot, thread_pool: QThreadPool) -> None:
    service = FakeShipmentService(_shipment())
    page = _page(qtbot, thread_pool, service)
    page.table.selectRow(0)
    qtbot.mouseClick(page.change_status_button, Qt.MouseButton.LeftButton)
    dialog = cast(ChangeStatusDialog, page._status_dialog)
    qtbot.mouseClick(dialog.change_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not dialog.isVisible(), timeout=3_000)
    qtbot.waitUntil(lambda: page.table.item(0, 4).text() == "Sorting", timeout=3_000)
    page.table.selectRow(0)
    qtbot.mouseClick(page.details_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: page._details_dialog is not None and page._details_dialog.isVisible(),
        timeout=3_000,
    )
    details = cast(ShipmentDetailsDialog, page._details_dialog)
    labels = {label.text() for label in details.findChildren(QLabel)}
    assert "Shipment number" in labels
    assert "Tracking number" not in labels
    assert "Barcode" not in labels
    history = details.findChild(type(page.table), "shipmentHistoryTable")
    assert history is not None and history.rowCount() == 1


def test_problem_report_duplicate_resolve_and_invalid_recovery(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    service = FakeShipmentService(_shipment(status=ShipmentStatus.SORTING))
    page = _page(qtbot, thread_pool, service)
    page.table.selectRow(0)
    qtbot.mouseClick(page.report_problem_button, Qt.MouseButton.LeftButton)
    report = cast(ReportProblemDialog, page._problem_dialog)
    service.failures["report_problem"] = ShipmentProblemOpenError("raw")
    qtbot.mouseClick(report.report_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "unresolved" in report.status.message, timeout=3_000)
    qtbot.mouseClick(report.report_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not report.isVisible(), timeout=3_000)
    qtbot.waitUntil(lambda: page.table.item(0, 4).text() == "Problem", timeout=3_000)

    page.table.selectRow(0)
    qtbot.mouseClick(page.resolve_problem_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: page._resolve_dialog is not None, timeout=3_000)
    resolve = cast(ResolveProblemDialog, page._resolve_dialog)
    assert resolve.recovery_input.currentData() == ShipmentStatus.SORTING.value
    service.failures["resolve_problem"] = InvalidShipmentTransitionError("Invalid recovery")
    qtbot.mouseClick(resolve.resolve_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "Invalid recovery" in resolve.status.message, timeout=3_000)
    qtbot.mouseClick(resolve.resolve_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not resolve.isVisible(), timeout=3_000)


def test_archive_restore_confirmation_and_permission_gating(
    qtbot: QtBot, thread_pool: QThreadPool
) -> None:
    service = FakeShipmentService(_shipment())
    page = _page(qtbot, thread_pool, service)
    page.table.selectRow(0)
    qtbot.mouseClick(page.archive_button, Qt.MouseButton.LeftButton)
    confirmation = cast(ConfirmDialog, page._confirm_dialog)
    assert not any(call[0] == "archive_shipment" for call in service.calls)
    confirm = confirmation.findChild(QPushButton, "confirmAction")
    assert confirm is not None
    qtbot.mouseClick(confirm, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: any(call[0] == "archive_shipment" for call in service.calls), timeout=3_000
    )
    qtbot.waitUntil(lambda: page.table.item(0, 9).text() == "Yes", timeout=3_000)
    page.table.selectRow(0)
    qtbot.mouseClick(page.restore_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: any(call[0] == "restore_shipment" for call in service.calls), timeout=3_000
    )

    operator = _page(
        qtbot, thread_pool, FakeShipmentService(_shipment()), UserRole.WAREHOUSE_OPERATOR
    )
    assert operator.new_button.isVisible()
    assert not operator.edit_button.isVisible()
    assert not operator.resolve_problem_button.isVisible()
    assert not operator.archive_button.isVisible()
    operator.table.selectRow(0)
    qtbot.mouseClick(operator.change_status_button, Qt.MouseButton.LeftButton)
    operator_dialog = cast(ChangeStatusDialog, operator._status_dialog)
    assert not operator_dialog.override_input.isVisible()
