"""Asynchronous, permission-aware shipment operations page."""

from __future__ import annotations

import logging
from collections.abc import Callable
from math import ceil
from typing import cast

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from warehouse_control_center.application.dto import (
    ClientDTO,
    SessionContext,
    ShipmentDTO,
    ShipmentPage,
    ShipmentProblemDTO,
)
from warehouse_control_center.application.permissions import has_permission
from warehouse_control_center.application.services import ClientService, ShipmentService
from warehouse_control_center.domain.enums import Permission, ProblemType, ShipmentStatus
from warehouse_control_center.domain.shipment_workflow import can_transition
from warehouse_control_center.presentation.qt.dialogs.confirm_dialog import ConfirmDialog
from warehouse_control_center.presentation.qt.dialogs.shipment_dialogs import (
    ChangeStatusDialog,
    ControlWeightDialog,
    EditShipmentDialog,
    NewShipmentDialog,
    ReportProblemDialog,
    ResolveProblemDialog,
    ShipmentDetailsData,
    ShipmentDetailsDialog,
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

MutationSuccess = str | Callable[[object], str]


class ShipmentsPage(QWidget):
    session_invalidated = Signal()

    _HEADERS = (
        "Shipment Number",
        "Recipient",
        "City",
        "Phone",
        "Status",
        "Packages",
        "Declared Weight",
        "Courier",
        "Problem",
        "Archived",
        "Created At",
        "Updated At",
    )
    _SORTS = (
        ("Received", "received_at"),
        ("Updated", "updated_at"),
        ("Shipment number", "shipment_number"),
        ("Recipient", "recipient_name"),
        ("City", "recipient_city"),
        ("Status", "status"),
    )

    def __init__(
        self,
        session: SessionContext,
        shipments: ShipmentService,
        thread_pool: QThreadPool,
        logger: logging.Logger,
        timezone_name: str,
        parent: QWidget | None = None,
        *,
        clients: ClientService | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("shipments_page")
        self._session = session
        self._shipments = shipments
        self._clients = clients
        self._logger = logger
        self._timezone_name = timezone_name
        self._tasks = DatabaseTaskRunner(thread_pool, self)
        self._records: dict[int, ShipmentDTO] = {}
        self._page = 1
        self._total = 0
        self._load_generation = 0
        self._load_busy = False
        self._mutation_busy = False
        self._pending_success: str | None = None
        self._new_dialog: NewShipmentDialog | None = None
        self._edit_dialog: EditShipmentDialog | None = None
        self._status_dialog: ChangeStatusDialog | None = None
        self._problem_dialog: ReportProblemDialog | None = None
        self._resolve_dialog: ResolveProblemDialog | None = None
        self._details_dialog: ShipmentDetailsDialog | None = None
        self._confirm_dialog: ConfirmDialog | None = None
        self._control_weight_dialog: ControlWeightDialog | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        title_row = QHBoxLayout()
        title = QLabel("Shipments")
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.refresh_button = self._button(
            "Refresh", "refreshShipments", self.refresh, secondary=True
        )
        title_row.addWidget(self.refresh_button)
        self.new_button = self._button("New Shipment", "openNewShipment", self.open_new)
        self.new_button.setVisible(has_permission(session, Permission.CREATE_SHIPMENT))
        title_row.addWidget(self.new_button)
        layout.addLayout(title_row)

        self.status = StatusBanner()
        layout.addWidget(self.status)
        layout.addWidget(self._build_filters())

        self.table = QTableWidget(0, len(self._HEADERS))
        self.table.setObjectName("shipmentsTable")
        self.table.setHorizontalHeaderLabels(self._HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._update_action_state)
        self.table.cellDoubleClicked.connect(lambda row, column: self.open_details())
        layout.addWidget(self.table, 1)

        pagination = QHBoxLayout()
        self.previous_button = self._button(
            "Previous", "previousShipmentPage", self.previous_page, secondary=True
        )
        self.next_button = self._button("Next", "nextShipmentPage", self.next_page, secondary=True)
        self.page_label = QLabel("Page 1 of 1 • 0 results")
        self.page_label.setObjectName("shipmentPageSummary")
        self.page_size_input = QComboBox()
        self.page_size_input.setObjectName("shipmentPageSize")
        for size in (25, 50, 100, 200):
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
        self.details_button = self._button(
            "Details", "shipmentDetails", self.open_details, secondary=True
        )
        self.edit_button = self._button("Edit", "editShipment", self.open_edit)
        self.change_status_button = self._button(
            "Change Status", "changeShipmentStatus", self.open_change_status
        )
        self.report_problem_button = self._button(
            "Report Problem", "reportShipmentProblem", self.open_report_problem, secondary=True
        )
        self.resolve_problem_button = self._button(
            "Resolve Problem", "resolveShipmentProblem", self.open_resolve_problem
        )
        self.control_weight_button = self._button(
            "Control Weight", "controlShipmentWeight", self.open_control_weight
        )
        self.archive_button = self._button(
            "Archive", "archiveShipment", self.archive, secondary=True, danger=True
        )
        self.restore_button = self._button("Restore", "restoreShipment", self.restore)
        visibility = (
            (self.edit_button, Permission.EDIT_SHIPMENT),
            (self.change_status_button, Permission.CHANGE_SHIPMENT_STATUS),
            (self.report_problem_button, Permission.MARK_PROBLEM),
            (self.resolve_problem_button, Permission.RESOLVE_PROBLEM),
            (self.control_weight_button, Permission.CONTROL_WEIGHT_SHIPMENT),
            (self.archive_button, Permission.ARCHIVE_SHIPMENT),
            (self.restore_button, Permission.RESTORE_SHIPMENT),
        )
        for button, permission in visibility:
            button.setVisible(has_permission(session, permission))
        for button in self._action_buttons():
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self._update_action_state()
        QTimer.singleShot(0, self.refresh)

    def _build_filters(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("filterCard")
        form = QFormLayout(frame)
        form.setContentsMargins(14, 12, 14, 12)
        form.setSpacing(10)
        first = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setObjectName("shipmentSearch")
        self.search_input.setPlaceholderText("Shipment number, recipient, phone, sender…")
        self.search_input.returnPressed.connect(self.apply_filters)
        self.status_input = QComboBox()
        self.status_input.setObjectName("shipmentStatusFilter")
        self.status_input.addItem("All statuses", None)
        for status in ShipmentStatus:
            self.status_input.addItem(display_enum(status.value), status.value)
        self.city_input = QLineEdit()
        self.city_input.setObjectName("shipmentCityFilter")
        self.city_input.setPlaceholderText("All cities")
        self.city_input.returnPressed.connect(self.apply_filters)
        first.addWidget(self.search_input, 2)
        first.addWidget(self.status_input)
        first.addWidget(self.city_input)
        form.addRow("Search", first)
        second = QHBoxLayout()
        self.courier_input = QSpinBox()
        self.courier_input.setObjectName("shipmentCourierFilter")
        self.courier_input.setRange(0, 2_147_483_647)
        self.courier_input.setSpecialValueText("All couriers")
        self.problem_only_input = QCheckBox("Open problems only")
        self.problem_only_input.setObjectName("shipmentProblemOnly")
        self.include_archived_input = QCheckBox("Include archived")
        self.include_archived_input.setObjectName("shipmentIncludeArchived")
        self.sort_input = QComboBox()
        self.sort_input.setObjectName("shipmentSort")
        for label, value in self._SORTS:
            self.sort_input.addItem(label, value)
        self.direction_input = QComboBox()
        self.direction_input.setObjectName("shipmentSortDirection")
        self.direction_input.addItem("Newest / Z–A", "desc")
        self.direction_input.addItem("Oldest / A–Z", "asc")
        self.apply_button = self._button("Apply", "applyShipmentFilters", self.apply_filters)
        self.clear_button = self._button(
            "Clear", "clearShipmentFilters", self.clear_filters, secondary=True
        )
        for widget in (
            self.courier_input,
            self.problem_only_input,
            self.include_archived_input,
            self.sort_input,
            self.direction_input,
            self.apply_button,
            self.clear_button,
        ):
            second.addWidget(widget)
        second.addStretch(1)
        form.addRow("Filters", second)
        return frame

    @staticmethod
    def _button(
        label: str,
        name: str,
        callback: Callable[[], None],
        *,
        secondary: bool = False,
        danger: bool = False,
    ) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName(name)
        button.setProperty("secondary", secondary)
        button.setProperty("danger", danger)
        button.clicked.connect(callback)
        return button

    def apply_filters(self) -> None:
        self._page = 1
        self.refresh()

    def clear_filters(self) -> None:
        self.search_input.clear()
        self.status_input.setCurrentIndex(0)
        self.city_input.clear()
        self.courier_input.setValue(0)
        self.problem_only_input.setChecked(False)
        self.include_archived_input.setChecked(False)
        self.sort_input.setCurrentIndex(0)
        self.direction_input.setCurrentIndex(0)
        self.apply_filters()

    def _page_size_changed(self) -> None:
        self._page = 1
        self.refresh()

    def previous_page(self) -> None:
        if self._page > 1:
            self._page -= 1
            self.refresh()

    def next_page(self) -> None:
        if self._page < self._page_count():
            self._page += 1
            self.refresh()

    def refresh(self) -> None:
        selected = self.selected_shipment()
        selected_id = selected.id if selected is not None else None
        self._load_generation += 1
        generation = self._load_generation
        self._load_busy = True
        self._update_busy_state()
        if self._pending_success is None:
            self.status.clear()
        try:
            status_value = self.status_input.currentData()
            status_filter = ShipmentStatus(status_value) if status_value else None
        except ValueError:
            status_filter = None
        courier_value = self.courier_input.value()
        page_size = cast(int, self.page_size_input.currentData())
        search = self.search_input.text()
        city = self.city_input.text()
        sort_by = cast(str, self.sort_input.currentData())
        direction = cast(str, self.direction_input.currentData())
        include_archived = self.include_archived_input.isChecked()
        problem_only = self.problem_only_input.isChecked()
        self._tasks.submit(
            lambda: self._shipments.list_shipments(
                self._session,
                page=self._page,
                page_size=page_size,
                search=search or None,
                status=status_filter,
                courier_id=courier_value or None,
                city=city or None,
                include_archived=include_archived,
                problem_only=problem_only,
                sort_by=sort_by,
                sort_direction=direction,
            ),
            on_result=lambda result: self._populate(generation, selected_id, result),
            on_error=lambda error: self._load_error(generation, error),
            on_finished=lambda: self._load_finished(generation),
        )

    def _populate(self, generation: int, selected_id: int | None, result: object) -> None:
        if generation != self._load_generation:
            return
        page = cast(ShipmentPage, result)
        self._page = page.page
        self._total = page.total
        if page.page > self._page_count():
            self._page = self._page_count()
            self.refresh()
            return
        self._records = {record.id: record for record in page.items}
        self.table.setRowCount(len(page.items))
        selected_row = -1
        for row, record in enumerate(page.items):
            values = (
                record.shipment_number,
                record.recipient_name,
                record.recipient_city,
                record.recipient_phone,
                display_enum(record.status.value),
                str(record.package_count),
                (
                    f"{record.declared_weight_g / 1000:g} kg"
                    if record.declared_weight_g is not None
                    else "—"
                ),
                str(record.courier_id) if record.courier_id else "Unassigned",
                "Yes" if record.status is ShipmentStatus.PROBLEM else "No",
                "Yes" if record.archived_at is not None else "No",
                display_timestamp(record.created_at, self._timezone_name),
                display_timestamp(record.updated_at, self._timezone_name),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, record.id)
                self.table.setItem(row, column, item)
            if record.id == selected_id:
                selected_row = row
        self.table.resizeColumnsToContents()
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        self._update_page_summary()
        if self._pending_success is not None:
            self.status.show_message(self._pending_success, status="success")
            self._pending_success = None
        elif not page.items:
            self.status.show_message("No shipments found.", status="warning")
        self._update_action_state()

    def _load_error(self, generation: int, error: BaseException) -> None:
        if generation == self._load_generation:
            self._handle_error(error, "load shipments")

    def _load_finished(self, generation: int) -> None:
        if generation == self._load_generation:
            self._load_busy = False
            self._update_busy_state()

    def _page_count(self) -> int:
        page_size = self.page_size_input.currentData()
        size = page_size if isinstance(page_size, int) and page_size > 0 else 50
        return max(1, ceil(self._total / size))

    def _update_page_summary(self) -> None:
        pages = self._page_count()
        self.page_label.setText(f"Page {self._page} of {pages} • {self._total} results")
        self.previous_button.setEnabled(not self._load_busy and self._page > 1)
        self.next_button.setEnabled(not self._load_busy and self._page < pages)

    def selected_shipment(self) -> ShipmentDTO | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        shipment_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return self._records.get(shipment_id) if isinstance(shipment_id, int) else None

    def open_new(self) -> None:
        if self._clients is None:
            self._show_new_dialog(())
            return
        if self._mutation_busy:
            return
        clients_service = self._clients
        self._mutation_busy = True
        self._update_busy_state()
        self._tasks.submit(
            lambda: clients_service.list_clients(self._session, active_only=True),
            on_result=lambda result: self._show_new_dialog(cast(tuple[ClientDTO, ...], result)),
            on_error=lambda error: self._handle_error(error, "load contract clients"),
            on_finished=self._mutation_finished,
        )

    def _show_new_dialog(self, clients: tuple[ClientDTO, ...]) -> None:
        dialog = NewShipmentDialog(clients, self)
        self._new_dialog = dialog
        dialog.create_requested.connect(lambda values: self._create(dialog, values))
        dialog.open()

    def _create(self, dialog: NewShipmentDialog, values: object) -> None:
        fields = cast(dict[str, object], values)
        dialog.set_busy(True)
        self._mutate(
            lambda: self._shipments.create_shipment(
                self._session,
                sender_name=cast(str, fields["sender_name"]),
                sender_client_id=cast(int | None, fields["sender_client_id"]),
                recipient_name=cast(str, fields["recipient_name"]),
                recipient_phone=cast(str, fields["recipient_phone"]),
                recipient_address=cast(str, fields["recipient_address"]),
                recipient_city=cast(str, fields["recipient_city"]),
                package_count=cast(int, fields["package_count"]),
                length_cm=cast(str | None, fields["length_cm"]),
                width_cm=cast(str | None, fields["width_cm"]),
                height_cm=cast(str | None, fields["height_cm"]),
                declared_weight_g=cast(int | None, fields["declared_weight_g"]),
                notes=cast(str | None, fields["notes"]),
            ),
            "create shipment",
            lambda result: (
                "Shipment created successfully. Shipment number: "
                f"{cast(ShipmentDTO, result).shipment_number}"
            ),
            dialog,
        )

    def open_edit(self) -> None:
        shipment = self.selected_shipment()
        if shipment is None:
            return
        dialog = EditShipmentDialog(shipment, self)
        self._edit_dialog = dialog
        dialog.update_requested.connect(lambda values: self._update(dialog, shipment, values))
        dialog.open()

    def _update(self, dialog: EditShipmentDialog, shipment: ShipmentDTO, values: object) -> None:
        fields = cast(dict[str, str | None], values)
        dialog.set_busy(True)
        self._mutate(
            lambda: self._shipments.update_shipment(
                self._session,
                shipment.id,
                expected_version=shipment.version,
                sender_name=cast(str, fields["sender_name"]),
                recipient_name=cast(str, fields["recipient_name"]),
                recipient_phone=cast(str, fields["recipient_phone"]),
                recipient_address=cast(str, fields["recipient_address"]),
                recipient_city=cast(str, fields["recipient_city"]),
                notes=fields["notes"],
            ),
            "update shipment",
            "Shipment updated successfully.",
            dialog,
        )

    def open_details(self) -> None:
        shipment = self.selected_shipment()
        if shipment is None or self._mutation_busy:
            return
        self._mutation_busy = True
        self._update_busy_state()

        def load() -> ShipmentDetailsData:
            current = self._shipments.get_shipment(self._session, shipment.id)
            history = self._shipments.get_status_history(self._session, shipment.id)
            problem = self._shipments.get_open_problem(self._session, shipment.id)
            weight_checks = self._shipments.get_weight_checks(self._session, shipment.id)
            return ShipmentDetailsData(current, history, problem, weight_checks)

        self._tasks.submit(
            load,
            on_result=self._show_details,
            on_error=lambda error: self._handle_error(error, "load shipment details"),
            on_finished=self._mutation_finished,
        )

    def _show_details(self, result: object) -> None:
        dialog = ShipmentDetailsDialog(cast(ShipmentDetailsData, result), self._timezone_name, self)
        self._details_dialog = dialog
        dialog.open()

    def open_control_weight(self) -> None:
        shipment = self.selected_shipment()
        if shipment is None:
            return
        dialog = ControlWeightDialog(shipment, self)
        self._control_weight_dialog = dialog
        dialog.record_requested.connect(
            lambda measured, note: self._record_control_weight(dialog, shipment, measured, note)
        )
        dialog.open()

    def _record_control_weight(
        self,
        dialog: ControlWeightDialog,
        shipment: ShipmentDTO,
        measured_weight_g: int,
        note: object,
    ) -> None:
        dialog.set_busy(True)
        self._mutate(
            lambda: self._shipments.record_control_weight(
                self._session,
                shipment.id,
                measured_weight_g=measured_weight_g,
                note=cast(str | None, note),
            ),
            "record shipment control weight",
            "Control weight recorded successfully.",
            dialog,
        )

    def open_change_status(self) -> None:
        shipment = self.selected_shipment()
        if shipment is None:
            return
        dialog = ChangeStatusDialog(
            shipment,
            allow_override=has_permission(self._session, Permission.OVERRIDE_STATUS_TRANSITION),
            parent=self,
        )
        self._status_dialog = dialog
        dialog.change_requested.connect(
            lambda target, reason, override: self._change_status(
                dialog, shipment, target, reason, override
            )
        )
        dialog.open()

    def _change_status(
        self,
        dialog: ChangeStatusDialog,
        shipment: ShipmentDTO,
        target: object,
        reason: str,
        override: bool,
    ) -> None:
        if not isinstance(target, ShipmentStatus):
            return
        dialog.set_busy(True)
        self._mutate(
            lambda: self._shipments.change_status(
                self._session,
                shipment.id,
                target,
                expected_version=shipment.version,
                reason=reason or None,
                override=override,
            ),
            "change shipment status",
            "Shipment status changed successfully.",
            dialog,
        )

    def open_report_problem(self) -> None:
        shipment = self.selected_shipment()
        if shipment is None:
            return
        dialog = ReportProblemDialog(self)
        self._problem_dialog = dialog
        dialog.report_requested.connect(
            lambda problem_type, description: self._report_problem(
                dialog, shipment, problem_type, description
            )
        )
        dialog.open()

    def _report_problem(
        self,
        dialog: ReportProblemDialog,
        shipment: ShipmentDTO,
        problem_type: object,
        description: str,
    ) -> None:
        if not isinstance(problem_type, ProblemType):
            return
        dialog.set_busy(True)
        self._mutate(
            lambda: self._shipments.report_problem(
                self._session,
                shipment.id,
                problem_type,
                expected_version=shipment.version,
                description=description or None,
            ),
            "report shipment problem",
            "Shipment problem reported successfully.",
            dialog,
        )

    def open_resolve_problem(self) -> None:
        shipment = self.selected_shipment()
        if shipment is None or self._mutation_busy:
            return
        self._mutation_busy = True
        self._update_busy_state()
        self._tasks.submit(
            lambda: self._shipments.get_open_problem(self._session, shipment.id),
            on_result=lambda result: self._show_resolve_dialog(shipment, result),
            on_error=lambda error: self._handle_error(error, "load shipment problem"),
            on_finished=self._mutation_finished,
        )

    def _show_resolve_dialog(self, shipment: ShipmentDTO, result: object) -> None:
        problem = cast(ShipmentProblemDTO | None, result)
        if problem is None:
            self.status.show_message("Shipment has no unresolved problem.")
            return
        dialog = ResolveProblemDialog(problem, self)
        self._resolve_dialog = dialog
        dialog.resolve_requested.connect(
            lambda target, reason: self._resolve_problem(dialog, shipment, target, reason)
        )
        dialog.open()

    def _resolve_problem(
        self,
        dialog: ResolveProblemDialog,
        shipment: ShipmentDTO,
        target: object,
        reason: str,
    ) -> None:
        if not isinstance(target, ShipmentStatus):
            return
        dialog.set_busy(True)
        self._mutate(
            lambda: self._shipments.resolve_problem(
                self._session,
                shipment.id,
                expected_version=shipment.version,
                recovery_status=target,
                reason=reason or None,
            ),
            "resolve shipment problem",
            "Shipment problem resolved successfully.",
            dialog,
        )

    def archive(self) -> None:
        shipment = self.selected_shipment()
        if shipment is None:
            return
        dialog = ConfirmDialog(
            "Archive shipment",
            f"Archive shipment {shipment.shipment_number}? It will remain recoverable.",
            destructive=True,
            parent=self,
        )
        self._confirm_dialog = dialog
        dialog.accepted.connect(lambda: self._archive_confirmed(shipment))
        dialog.open()

    def _archive_confirmed(self, shipment: ShipmentDTO) -> None:
        self._mutate(
            lambda: self._shipments.archive_shipment(
                self._session, shipment.id, expected_version=shipment.version
            ),
            "archive shipment",
            "Shipment archived successfully.",
        )

    def restore(self) -> None:
        shipment = self.selected_shipment()
        if shipment is not None:
            self._mutate(
                lambda: self._shipments.restore_shipment(
                    self._session, shipment.id, expected_version=shipment.version
                ),
                "restore shipment",
                "Shipment restored successfully.",
            )

    def _mutate(
        self,
        operation: Callable[[], object],
        context: str,
        success: MutationSuccess,
        dialog: NewShipmentDialog
        | EditShipmentDialog
        | ChangeStatusDialog
        | ReportProblemDialog
        | ResolveProblemDialog
        | ControlWeightDialog
        | None = None,
    ) -> None:
        if self._mutation_busy:
            return
        self._mutation_busy = True
        self._update_busy_state()
        self.status.clear()
        self._tasks.submit(
            operation,
            on_result=lambda result: self._mutation_complete(result, success, dialog),
            on_error=lambda error: self._mutation_error(error, context, dialog),
            on_finished=self._mutation_finished,
        )

    def _mutation_complete(
        self,
        result: object,
        success: MutationSuccess,
        dialog: NewShipmentDialog
        | EditShipmentDialog
        | ChangeStatusDialog
        | ReportProblemDialog
        | ResolveProblemDialog
        | ControlWeightDialog
        | None,
    ) -> None:
        if dialog is not None:
            dialog.accept()
        self._pending_success = success(result) if callable(success) else success
        self.refresh()

    def _mutation_error(
        self,
        error: BaseException,
        context: str,
        dialog: NewShipmentDialog
        | EditShipmentDialog
        | ChangeStatusDialog
        | ReportProblemDialog
        | ResolveProblemDialog
        | ControlWeightDialog
        | None,
    ) -> None:
        presentation = translate_error(error)
        if presentation.session_invalid:
            if dialog is not None:
                dialog.reject()
            self.session_invalidated.emit()
            return
        if presentation.unexpected:
            log_unexpected(self._logger, error, context)
        if dialog is not None:
            dialog.show_error(presentation.message)
        else:
            self.status.show_message(presentation.message)

    def _mutation_finished(self) -> None:
        self._mutation_busy = False
        self._update_busy_state()

    def _handle_error(self, error: BaseException, context: str) -> None:
        presentation = translate_error(error)
        if presentation.session_invalid:
            self.session_invalidated.emit()
            return
        if presentation.unexpected:
            log_unexpected(self._logger, error, context)
        self.status.show_message(presentation.message)

    def _update_busy_state(self) -> None:
        busy = self._load_busy or self._mutation_busy
        self.refresh_button.setEnabled(not busy)
        self.apply_button.setEnabled(not busy)
        self.clear_button.setEnabled(not busy)
        self.new_button.setEnabled(not busy)
        self.page_size_input.setEnabled(not busy)
        if busy:
            for button in self._action_buttons():
                button.setEnabled(False)
            self.previous_button.setEnabled(False)
            self.next_button.setEnabled(False)
        else:
            self._update_page_summary()
            self._update_action_state()

    def _action_buttons(self) -> tuple[QPushButton, ...]:
        return (
            self.details_button,
            self.edit_button,
            self.change_status_button,
            self.report_problem_button,
            self.resolve_problem_button,
            self.control_weight_button,
            self.archive_button,
            self.restore_button,
        )

    def _update_action_state(self) -> None:
        if self._load_busy or self._mutation_busy:
            return
        shipment = self.selected_shipment()
        for button in self._action_buttons():
            button.setEnabled(shipment is not None)
        if shipment is None:
            return
        operational = shipment.archived_at is None
        problem = shipment.status is ShipmentStatus.PROBLEM
        normal_status_available = any(
            target is not ShipmentStatus.PROBLEM and can_transition(shipment.status, target)
            for target in ShipmentStatus
        )
        can_override = has_permission(self._session, Permission.OVERRIDE_STATUS_TRANSITION)
        self.edit_button.setEnabled(operational)
        self.change_status_button.setEnabled(
            operational and not problem and (normal_status_available or can_override)
        )
        self.report_problem_button.setEnabled(
            operational and can_transition(shipment.status, ShipmentStatus.PROBLEM)
        )
        self.resolve_problem_button.setEnabled(operational and problem)
        self.control_weight_button.setEnabled(
            operational and shipment.declared_weight_g is not None
        )
        self.archive_button.setEnabled(operational)
        self.restore_button.setEnabled(not operational)
