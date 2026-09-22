"""Permission-driven desktop shell; future business pages remain honest placeholders."""

import logging

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QWidget

from warehouse_control_center.application.dto import SessionContext
from warehouse_control_center.application.services import UserService
from warehouse_control_center.presentation.qt.pages import PlaceholderPage, UsersPage
from warehouse_control_center.presentation.qt.widgets.sidebar import Sidebar


class MainWindow(QMainWindow):
    logout_requested = Signal()
    session_invalidated = Signal()
    application_close_requested = Signal()

    _PAGE_TITLES = {
        "dashboard": "Dashboard",
        "shipments": "Shipments",
        "scan": "Scan",
        "couriers": "Couriers",
        "reports": "Reports",
        "audit": "Audit Log",
        "settings": "Settings",
    }

    def __init__(
        self,
        session: SessionContext,
        users: UserService,
        thread_pool: QThreadPool,
        logger: logging.Logger,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Warehouse Control Center")
        self.setMinimumSize(1200, 750)
        self.resize(1320, 820)
        root = QWidget()
        root.setObjectName("contentRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.sidebar = Sidebar(session)
        self.sidebar.navigate.connect(self.show_page)
        self.sidebar.logout_requested.connect(self.logout_requested)
        root_layout.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        root_layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self._page_indexes: dict[str, int] = {}
        for route in self.sidebar.routes():
            page: QWidget
            if route == "users":
                page = UsersPage(session, users, thread_pool, logger)
                page.session_invalidated.connect(self.session_invalidated)
            else:
                page = PlaceholderPage(self._PAGE_TITLES[route])
            self._page_indexes[route] = self.stack.addWidget(page)

        first = self.sidebar.first_route()
        if first is not None:
            self.show_page(first)

    def show_page(self, route: str) -> None:
        index = self._page_indexes.get(route)
        if index is None:
            return
        self.stack.setCurrentIndex(index)
        self.sidebar.select(route)

    def has_route(self, route: str) -> bool:
        return route in self._page_indexes

    def page(self, route: str) -> QWidget | None:
        index = self._page_indexes.get(route)
        return self.stack.widget(index) if index is not None else None

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.application_close_requested.emit()
