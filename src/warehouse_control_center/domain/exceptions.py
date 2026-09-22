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
