"""Central role-to-capability policy used by all present and future service layers."""

from warehouse_control_center.application.dto import SessionContext
from warehouse_control_center.domain.enums import Permission, UserRole
from warehouse_control_center.domain.exceptions import (
    PasswordChangeRequiredError,
    PermissionDeniedError,
)

_OPERATOR_PERMISSIONS = frozenset(
    {
        Permission.VIEW_SHIPMENTS,
        Permission.CREATE_SHIPMENT,
        Permission.CHANGE_SHIPMENT_STATUS,
        Permission.ASSIGN_SHIPMENT,
        Permission.MARK_PROBLEM,
        Permission.VIEW_COURIERS,
        Permission.VIEW_CLIENTS,
        Permission.CONTROL_WEIGHT_SHIPMENT,
    }
)

_ADMIN_PERMISSIONS = frozenset(
    {
        Permission.VIEW_SHIPMENTS,
        Permission.CREATE_SHIPMENT,
        Permission.EDIT_SHIPMENT,
        Permission.CHANGE_SHIPMENT_STATUS,
        Permission.ASSIGN_SHIPMENT,
        Permission.MARK_PROBLEM,
        Permission.RESOLVE_PROBLEM,
        Permission.OVERRIDE_STATUS_TRANSITION,
        Permission.ARCHIVE_SHIPMENT,
        Permission.RESTORE_SHIPMENT,
        Permission.VIEW_DASHBOARD,
        Permission.VIEW_REPORTS,
        Permission.EXPORT_REPORTS,
        Permission.IMPORT_SHIPMENTS,
        Permission.VIEW_COURIERS,
        Permission.MANAGE_COURIERS,
        Permission.VIEW_CLIENTS,
        Permission.MANAGE_CLIENTS,
        Permission.CONTROL_WEIGHT_SHIPMENT,
        Permission.VIEW_AUDIT_LOG,
        Permission.MANAGE_USERS,
        Permission.MANAGE_SETTINGS,
        Permission.CREATE_BACKUP,
    }
)

ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.ADMIN: _ADMIN_PERMISSIONS,
    UserRole.WAREHOUSE_OPERATOR: _OPERATOR_PERMISSIONS,
    UserRole.SUPERVISOR: _OPERATOR_PERMISSIONS
    | frozenset(
        {
            Permission.EDIT_SHIPMENT,
            Permission.RESOLVE_PROBLEM,
            Permission.VIEW_DASHBOARD,
            Permission.VIEW_REPORTS,
            Permission.EXPORT_REPORTS,
            Permission.IMPORT_SHIPMENTS,
            Permission.VIEW_AUDIT_LOG,
        }
    ),
}


def has_permission(session: SessionContext, permission: Permission) -> bool:
    if session.must_change_password:
        return False
    permissions = ROLE_PERMISSIONS.get(session.role)
    return permissions is not None and permission in permissions


def require_permission(session: SessionContext, permission: Permission) -> None:
    if session.must_change_password:
        raise PasswordChangeRequiredError("Password change is required before this action")
    permissions = ROLE_PERMISSIONS.get(session.role)
    if permissions is None or permission not in permissions:
        permission_name = (
            permission.value if isinstance(permission, Permission) else str(permission)
        )
        raise PermissionDeniedError(f"Permission required: {permission_name}")
