"""Atomic own-password change workflow shared by public service facades."""

from warehouse_control_center.application.dto import SessionContext
from warehouse_control_center.application.ports.clock import Clock
from warehouse_control_center.application.ports.passwords import PasswordHasher
from warehouse_control_center.application.ports.unit_of_work import UnitOfWorkFactory
from warehouse_control_center.application.services._audit import make_audit_event
from warehouse_control_center.application.services._time import utc_timestamp
from warehouse_control_center.domain.enums import AuditAction
from warehouse_control_center.domain.exceptions import (
    InvalidCurrentPasswordError,
    InvalidPasswordError,
    InvalidUserStateError,
    UserNotFoundError,
)
from warehouse_control_center.domain.validation import validate_password


class PasswordChangeService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        password_hasher: PasswordHasher,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._password_hasher = password_hasher
        self._clock = clock

    def change_password(
        self,
        session: SessionContext,
        current_password: str,
        new_password: str,
    ) -> SessionContext:
        validate_password(new_password)
        with self._uow_factory() as uow:
            uow.users.lock_for_administration()
            now = utc_timestamp(self._clock.now())
            try:
                user = uow.users.get_by_id(session.user_id)
            except InvalidPasswordError:
                raise InvalidUserStateError(
                    "Stored credential is invalid; administrator reset is required"
                ) from None
            if user is None:
                raise UserNotFoundError("Current user no longer exists")
            if not user.active or user.archived_at is not None:
                raise InvalidUserStateError("Current user is not active")
            if not self._password_hasher.verify_password(user.password_hash, current_password):
                raise InvalidCurrentPasswordError("Current password is incorrect")
            if self._password_hasher.verify_password(user.password_hash, new_password):
                raise InvalidPasswordError("New password must differ from the current password")

            user.password_hash = self._password_hasher.hash_password(new_password)
            user.credential_version += 1
            user.must_change_password = False
            user.failed_login_attempts = 0
            user.locked_until = None
            user.updated_at = now
            saved = uow.users.save(user)
            uow.audits.add(
                make_audit_event(
                    action=AuditAction.PASSWORD_CHANGED,
                    actor_id=saved.id,
                    actor_name=saved.username,
                    entity_id=saved.id or session.user_id,
                    timestamp=now,
                )
            )
            uow.commit()

        return SessionContext(
            user_id=saved.id or session.user_id,
            username=saved.username,
            role=saved.role,
            authenticated_at=now,
            must_change_password=False,
            credential_version=saved.credential_version,
        )
