"""Translate application failures into safe, consistent UI messages."""

import logging
from dataclasses import dataclass

from warehouse_control_center.domain.exceptions import (
    AuthenticationError,
    DatabaseBusyError,
    DuplicateBarcodeError,
    DuplicateTrackingNumberError,
    DuplicateUserError,
    InvalidCurrentPasswordError,
    InvalidShipmentTransitionError,
    InvalidUserStateError,
    LastActiveAdministratorError,
    PasswordChangeRequiredError,
    PermissionDeniedError,
    ShipmentArchivedError,
    ShipmentConflictError,
    ShipmentNotFoundError,
    ShipmentProblemNotFoundError,
    ShipmentProblemOpenError,
    UserNotFoundError,
    ValidationError,
)


@dataclass(frozen=True, slots=True)
class UIError:
    message: str
    retryable: bool = False
    session_invalid: bool = False
    unexpected: bool = False


def translate_error(error: BaseException) -> UIError:
    """Return a presentation-safe description without infrastructure details."""
    if isinstance(error, DatabaseBusyError):
        return UIError(
            "The database is busy. Please wait a moment and try again.",
            retryable=True,
        )
    if isinstance(error, InvalidCurrentPasswordError):
        return UIError("The current password is incorrect.")
    if isinstance(error, AuthenticationError):
        return UIError("Invalid username or password.")
    if isinstance(error, DuplicateUserError):
        return UIError("That username is already reserved.")
    if isinstance(error, DuplicateTrackingNumberError):
        return UIError("That tracking number is already reserved.")
    if isinstance(error, DuplicateBarcodeError):
        return UIError("That barcode is already reserved.")
    if isinstance(error, ShipmentConflictError):
        return UIError("This shipment was changed by another operation. Refresh and try again.")
    if isinstance(error, ShipmentNotFoundError):
        return UIError("The shipment no longer exists. Refresh the list and try again.")
    if isinstance(error, ShipmentArchivedError):
        return UIError("Archived shipments cannot be changed. Restore the shipment first.")
    if isinstance(error, ShipmentProblemOpenError):
        return UIError("This shipment already has an unresolved problem.")
    if isinstance(error, ShipmentProblemNotFoundError):
        return UIError("This shipment has no unresolved problem.")
    if isinstance(error, InvalidShipmentTransitionError):
        return UIError(str(error))
    if isinstance(error, LastActiveAdministratorError):
        return UIError("At least one active administrator must remain.")
    if isinstance(error, PasswordChangeRequiredError):
        return UIError("You must change your password before using this feature.")
    if isinstance(error, PermissionDeniedError):
        if "no longer authorized" in str(error).casefold():
            return UIError(
                "Your session is no longer valid. Please sign in again.",
                session_invalid=True,
            )
        return UIError("You do not have permission to perform this action.")
    if isinstance(error, (ValidationError, InvalidUserStateError, UserNotFoundError)):
        return UIError(str(error))
    return UIError("An unexpected error occurred.", unexpected=True)


def log_unexpected(logger: logging.Logger, error: BaseException, context: str) -> None:
    """Log an unexpected failure with its traceback while keeping it out of the UI."""
    logger.error(
        "Unexpected UI failure during %s",
        context,
        exc_info=(type(error), error, error.__traceback__),
    )
