"""Permission-driven application navigation."""

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from warehouse_control_center.application.dto import SessionContext
from warehouse_control_center.application.permissions import has_permission
from warehouse_control_center.domain.enums import Permission


@dataclass(frozen=True, slots=True)
class NavigationItem:
    route: str
    label: str
    permission: Permission


NAVIGATION_ITEMS = (
    NavigationItem("dashboard", "Dashboard", Permission.VIEW_DASHBOARD),
    NavigationItem("shipments", "Shipments", Permission.VIEW_SHIPMENTS),
    NavigationItem("sms_shipments", "SMS Shipments", Permission.VIEW_SHIPMENT_SMS),
    NavigationItem("clients", "Clients", Permission.VIEW_CLIENTS),
    NavigationItem("scan", "Scan", Permission.CREATE_SHIPMENT),
    NavigationItem("couriers", "Couriers", Permission.VIEW_COURIERS),
    NavigationItem("reports", "Reports", Permission.VIEW_REPORTS),
    NavigationItem("users", "Users", Permission.MANAGE_USERS),
    NavigationItem("audit", "Audit Log", Permission.VIEW_AUDIT_LOG),
    NavigationItem("settings", "Settings", Permission.MANAGE_SETTINGS),
)


class Sidebar(QFrame):
    navigate = Signal(str)
    logout_requested = Signal()

    def __init__(self, session: SessionContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(238)
        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 24, 14, 18)
        layout.setSpacing(8)
        brand = QLabel("WAREHOUSE\nCONTROL CENTER")
        brand.setStyleSheet("font-size: 17px; font-weight: 700; padding: 0 10px 18px;")
        layout.addWidget(brand)

        for item in NAVIGATION_ITEMS:
            if not has_permission(session, item.permission):
                continue
            button = QPushButton(item.label)
            button.setObjectName(f"nav_{item.route}")
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, route=item.route: self.navigate.emit(route)
            )
            self._group.addButton(button)
            self._buttons[item.route] = button
            layout.addWidget(button)

        layout.addStretch(1)
        identity = QLabel(f"{session.username}\n{session.role.value.replace('_', ' ').title()}")
        identity.setObjectName("sessionIdentity")
        identity.setStyleSheet("padding: 12px 10px; color: #aeb9ca;")
        layout.addWidget(identity)
        logout = QPushButton("Logout")
        logout.setObjectName("nav_logout")
        logout.clicked.connect(self.logout_requested)
        layout.addWidget(logout)

    def routes(self) -> set[str]:
        return set(self._buttons)

    def select(self, route: str) -> None:
        button = self._buttons.get(route)
        if button is not None:
            button.setChecked(True)

    def first_route(self) -> str | None:
        return next(iter(self._buttons), None)
