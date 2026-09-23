"""Application-specific exceptions that callers may handle intentionally."""


class WarehouseControlCenterError(Exception):
    """Base exception for expected application failures."""


class UnsafeDatabasePathError(WarehouseControlCenterError):
    """Raised when a test configuration could target production data."""


class UnsafeRuntimePathError(WarehouseControlCenterError):
    """Raised when writable runtime state overlaps an unsafe location."""


class DatabaseSchemaError(WarehouseControlCenterError):
    """Raised when the connected database is not at the supported schema revision."""


class DatabaseBusyError(WarehouseControlCenterError):
    """Raised when SQLite cannot acquire the required write lock in time."""


class ValidationError(WarehouseControlCenterError):
    """Base exception for invalid business input."""


class InvalidUsernameError(ValidationError):
    """Raised when a username violates the documented username policy."""


class InvalidPasswordError(ValidationError):
    """Raised when a password violates the password policy."""


class InvalidUserRoleError(ValidationError):
    """Raised when a value is not a supported user role."""


class AuthenticationError(WarehouseControlCenterError):
    """Generic authentication failure that does not reveal account state."""


class InvalidCurrentPasswordError(AuthenticationError):
    """Raised when an authenticated user supplies the wrong current password."""


class PermissionDeniedError(WarehouseControlCenterError):
    """Raised when a session lacks a required capability."""


class PasswordChangeRequiredError(PermissionDeniedError):
    """Raised when a restricted session attempts a protected action."""


class DuplicateUserError(WarehouseControlCenterError):
    """Raised when a normalized username is already reserved."""


class UserNotFoundError(WarehouseControlCenterError):
    """Raised when an administrative user target does not exist."""


class InvalidUserStateError(WarehouseControlCenterError):
    """Raised when a requested user-state transition is invalid."""


class LastActiveAdministratorError(WarehouseControlCenterError):
    """Raised when an operation would remove the last active administrator."""


class TemporaryCredentialConsumedError(WarehouseControlCenterError):
    """Raised when a one-time temporary password is requested more than once."""


class InvalidShipmentError(ValidationError):
    """Raised when shipment input violates the centralized shipment policy."""


class InvalidShipmentTransitionError(WarehouseControlCenterError):
    """Raised when a shipment workflow transition is not permitted."""


class ShipmentNotFoundError(WarehouseControlCenterError):
    """Raised when a requested shipment does not exist."""


class DuplicateTrackingNumberError(WarehouseControlCenterError):
    """Raised when a normalized tracking number is already reserved."""


class DuplicateBarcodeError(WarehouseControlCenterError):
    """Raised when a normalized barcode is already reserved."""


class ShipmentNumberExhaustedError(WarehouseControlCenterError):
    """Raised when the visible shipment-number range has no value remaining."""


class ShipmentNumberAllocationError(WarehouseControlCenterError):
    """Raised when the configured shipment-number sequence cannot allocate safely."""


class ShipmentConflictError(WarehouseControlCenterError):
    """Raised when optimistic concurrency detects a stale shipment version."""


class ShipmentArchivedError(WarehouseControlCenterError):
    """Raised when an operational mutation targets an archived shipment."""


class ShipmentProblemOpenError(WarehouseControlCenterError):
    """Raised when a shipment already has an unresolved problem."""


class ShipmentProblemNotFoundError(WarehouseControlCenterError):
    """Raised when problem resolution has no unresolved record to resolve."""


class InvalidShipmentQueryError(ValidationError):
    """Raised when shipment pagination, filtering, or sorting input is invalid."""
