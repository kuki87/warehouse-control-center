"""Fresh-session authorization shared by transactional application services."""

from warehouse_control_center.application.dto import SessionContext
from warehouse_control_center.application.permissions import has_permission, require_permission
from warehouse_control_center.application.ports.unit_of_work import UnitOfWork
from warehouse_control_center.domain.entities import User
from warehouse_control_center.domain.enums import Permission
from warehouse_control_center.domain.exceptions import (
    InvalidPasswordError,
    InvalidUserRoleError,
    PermissionDeniedError,
)


def require_current_actor(
    uow: UnitOfWork,
    session: SessionContext,
    permission: Permission,
) -> User:
    require_permission(session, permission)
    try:
        actor = uow.users.get_by_id(session.user_id)
    except (InvalidPasswordError, InvalidUserRoleError):
        raise PermissionDeniedError("Current session is no longer authorized") from None
    if (
        actor is None
        or actor.id is None
        or not actor.active
        or actor.archived_at is not None
        or actor.credential_version != session.credential_version
        or actor.username != session.username
    ):
        raise PermissionDeniedError("Current session is no longer authorized")
    current = SessionContext(
        user_id=actor.id,
        username=actor.username,
        role=actor.role,
        authenticated_at=session.authenticated_at,
        must_change_password=actor.must_change_password,
        credential_version=actor.credential_version,
    )
    if not has_permission(current, permission):
        raise PermissionDeniedError("Current session is no longer authorized")
    return actor
