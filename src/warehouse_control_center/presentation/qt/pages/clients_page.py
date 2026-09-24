"""Asynchronous contract-client administration page."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import cast

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from warehouse_control_center.application.dto import ClientDTO, SessionContext
from warehouse_control_center.application.permissions import has_permission
from warehouse_control_center.application.services import ClientService
from warehouse_control_center.domain.enums import Permission
from warehouse_control_center.presentation.qt.dialogs.client_dialogs import (
    ClientDetailsDialog,
    ClientDialog,
)
from warehouse_control_center.presentation.qt.dialogs.confirm_dialog import ConfirmDialog
from warehouse_control_center.presentation.qt.error_mapping import log_unexpected, translate_error
from warehouse_control_center.presentation.qt.widgets.status_banner import StatusBanner
from warehouse_control_center.presentation.qt.workers import DatabaseTaskRunner


class ClientsPage(QWidget):
    session_invalidated = Signal()

    _HEADERS = ("Client Code", "Company", "City", "Contact", "Phone", "Active")

    def __init__(
        self,
        session: SessionContext,
        clients: ClientService,
        thread_pool: QThreadPool,
        logger: logging.Logger,
        timezone_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("clients_page")
        self._session = session
        self._clients = clients
        self._logger = logger
        self._timezone_name = timezone_name
        self._tasks = DatabaseTaskRunner(thread_pool, self)
        self._records: dict[int, ClientDTO] = {}
        self._busy = False
        self._dialog: ClientDialog | None = None
        self._details_dialog: ClientDetailsDialog | None = None
        self._confirm_dialog: ConfirmDialog | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        title_row = QHBoxLayout()
        title = QLabel("Contract Clients")
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("clientSearch")
        self.search_input.setPlaceholderText("Code, company, city, contact…")
        self.search_input.returnPressed.connect(self.refresh)
        title_row.addWidget(self.search_input)
        self.refresh_button = self._button(
            "Refresh", "refreshClients", self.refresh, secondary=True
        )
        title_row.addWidget(self.refresh_button)
        self.create_button = self._button("New Client", "openCreateClient", self.open_create)
        self.create_button.setVisible(has_permission(session, Permission.MANAGE_CLIENTS))
        title_row.addWidget(self.create_button)
        layout.addLayout(title_row)

        self.status = StatusBanner()
        layout.addWidget(self.status)
        self.table = QTableWidget(0, len(self._HEADERS))
        self.table.setObjectName("clientsTable")
        self.table.setHorizontalHeaderLabels(self._HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.table.cellDoubleClicked.connect(lambda row, column: self.open_details())
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.details_button = self._button(
            "Details", "clientDetails", self.open_details, secondary=True
        )
        self.edit_button = self._button("Edit", "editClient", self.open_edit)
        self.activate_button = self._button("Activate", "activateClient", self.activate)
        self.deactivate_button = self._button(
            "Deactivate", "deactivateClient", self.deactivate, secondary=True
        )
        can_manage = has_permission(session, Permission.MANAGE_CLIENTS)
        for button in (self.edit_button, self.activate_button, self.deactivate_button):
            button.setVisible(can_manage)
        for button in self._action_buttons():
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self._update_actions()
        QTimer.singleShot(0, self.refresh)

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
        search = self.search_input.text()
        self._tasks.submit(
            lambda: self._clients.list_clients(self._session, search=search or None),
            on_result=self._populate,
            on_error=lambda error: self._handle_error(error, "load clients"),
            on_finished=lambda: self._set_busy(False),
        )

    def _populate(self, result: object) -> None:
        records = cast(tuple[ClientDTO, ...], result)
        self._records = {record.id: record for record in records}
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = (
                record.client_code,
                record.company_name,
                record.city,
                record.contact_name or "—",
                record.phone or "—",
                "Yes" if record.active else "No",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, record.id)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        if not records:
            self.status.show_message("No clients found.", status="warning")
        self._update_actions()

    def selected_client(self) -> ClientDTO | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        client_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return self._records.get(client_id) if isinstance(client_id, int) else None

    def open_create(self) -> None:
        self._open_dialog(None)

    def open_edit(self) -> None:
        client = self.selected_client()
        if client is not None:
            self._open_dialog(client)

    def _open_dialog(self, client: ClientDTO | None) -> None:
        dialog = ClientDialog(client, self)
        self._dialog = dialog
        dialog.save_requested.connect(lambda values: self._save(dialog, client, values))
        dialog.open()

    def _save(self, dialog: ClientDialog, client: ClientDTO | None, values: object) -> None:
        fields = cast(dict[str, object], values)
        dialog.set_busy(True)
        operation = (
            (
                lambda: self._clients.create_client(
                    self._session,
                    client_code=cast(str, fields["client_code"]),
                    company_name=cast(str, fields["company_name"]),
                    tax_id=cast(str | None, fields["tax_id"]),
                    address=cast(str, fields["address"]),
                    city=cast(str, fields["city"]),
                    contact_name=cast(str | None, fields["contact_name"]),
                    phone=cast(str | None, fields["phone"]),
                    email=cast(str | None, fields["email"]),
                    contract_number=cast(str | None, fields["contract_number"]),
                    contract_start=cast(date | None, fields["contract_start"]),
                    contract_end=cast(date | None, fields["contract_end"]),
                    notes=cast(str | None, fields["notes"]),
                )
            )
            if client is None
            else (lambda: self._clients.update_client(self._session, client.id, **fields))
        )
        self._mutate(operation, "save client", dialog)

    def open_details(self) -> None:
        client = self.selected_client()
        if client is None:
            return
        self._details_dialog = ClientDetailsDialog(client, self._timezone_name, self)
        self._details_dialog.open()

    def activate(self) -> None:
        client = self.selected_client()
        if client is not None:
            self._mutate(
                lambda: self._clients.activate_client(self._session, client.id), "activate client"
            )

    def deactivate(self) -> None:
        client = self.selected_client()
        if client is None:
            return
        dialog = ConfirmDialog(
            "Deactivate client",
            f"Deactivate {client.company_name}? Existing shipments are unchanged.",
            destructive=True,
            parent=self,
        )
        self._confirm_dialog = dialog
        dialog.accepted.connect(
            lambda: self._mutate(
                lambda: self._clients.deactivate_client(self._session, client.id),
                "deactivate client",
            )
        )
        dialog.open()

    def _mutate(
        self,
        operation: Callable[[], object],
        context: str,
        dialog: ClientDialog | None = None,
    ) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._tasks.submit(
            operation,
            on_result=lambda result: self._mutation_complete(dialog),
            on_error=lambda error: self._mutation_error(error, context, dialog),
            on_finished=lambda: self._set_busy(False),
        )

    def _mutation_complete(self, dialog: ClientDialog | None) -> None:
        if dialog is not None:
            dialog.accept()
        self.status.show_message("Client saved successfully.", status="success")
        QTimer.singleShot(0, self.refresh)

    def _mutation_error(
        self, error: BaseException, context: str, dialog: ClientDialog | None
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

    def _handle_error(self, error: BaseException, context: str) -> None:
        self._mutation_error(error, context, None)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.refresh_button.setEnabled(not busy)
        self.create_button.setEnabled(not busy)
        self.search_input.setEnabled(not busy)
        self._update_actions()

    def _action_buttons(self) -> tuple[QPushButton, ...]:
        return (
            self.details_button,
            self.edit_button,
            self.activate_button,
            self.deactivate_button,
        )

    def _update_actions(self) -> None:
        client = None if self._busy else self.selected_client()
        self.details_button.setEnabled(client is not None)
        self.edit_button.setEnabled(client is not None)
        self.activate_button.setEnabled(client is not None and not client.active)
        self.deactivate_button.setEnabled(client is not None and client.active)
