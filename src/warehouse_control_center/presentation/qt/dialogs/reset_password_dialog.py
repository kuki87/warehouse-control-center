"""Presentation alias for one-time administrator reset credentials."""

from PySide6.QtWidgets import QWidget

from warehouse_control_center.application.dto import TemporaryCredential
from warehouse_control_center.presentation.qt.dialogs.temporary_credential_dialog import (
    TemporaryCredentialDialog,
)


class ResetPasswordDialog(TemporaryCredentialDialog):
    def __init__(self, credential: TemporaryCredential, parent: QWidget | None = None) -> None:
        super().__init__(
            credential,
            title="Temporary password created",
            explanation=(
                "Give this password to the user through an appropriate channel. "
                "It is shown once and must be changed at the next sign-in."
            ),
            parent=parent,
        )
