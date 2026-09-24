"""Dialogs used by the desktop client."""

from warehouse_control_center.presentation.qt.dialogs.client_dialogs import (
    ClientDetailsDialog,
    ClientDialog,
)
from warehouse_control_center.presentation.qt.dialogs.confirm_dialog import ConfirmDialog
from warehouse_control_center.presentation.qt.dialogs.create_user_dialog import CreateUserDialog
from warehouse_control_center.presentation.qt.dialogs.password_change_dialog import (
    PasswordChangeDialog,
)
from warehouse_control_center.presentation.qt.dialogs.shipment_dialogs import (
    ChangeStatusDialog,
    ControlWeightDialog,
    EditShipmentDialog,
    NewShipmentDialog,
    ReportProblemDialog,
    ResolveProblemDialog,
    ShipmentDetailsDialog,
)
from warehouse_control_center.presentation.qt.dialogs.temporary_credential_dialog import (
    FirstRunDialog,
    TemporaryCredentialDialog,
)

__all__ = [
    "ConfirmDialog",
    "ClientDetailsDialog",
    "ClientDialog",
    "CreateUserDialog",
    "FirstRunDialog",
    "PasswordChangeDialog",
    "ChangeStatusDialog",
    "ControlWeightDialog",
    "EditShipmentDialog",
    "NewShipmentDialog",
    "ReportProblemDialog",
    "ResolveProblemDialog",
    "ShipmentDetailsDialog",
    "TemporaryCredentialDialog",
]
