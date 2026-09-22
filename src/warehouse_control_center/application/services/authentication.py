"""Authentication orchestration with persistent, bounded login throttling."""

import unicodedata

from warehouse_control_center.application.dto import SessionContext
from warehouse_control_center.application.ports.clock import Clock
from warehouse_control_center.application.ports.passwords import PasswordHasher
from warehouse_control_center.application.ports.unit_of_work import UnitOfWorkFactory
from warehouse_control_center.application.services._audit import make_audit_event
from warehouse_control_center.application.services._time import utc_timestamp
from warehouse_control_center.application.services.lockout import lockout_duration
from warehouse_control_center.application.services.password_change import PasswordChangeService
from warehouse_control_center.domain.enums import AuditAction
from warehouse_control_center.domain.exceptions import (
    AuthenticationError,
    InvalidPasswordError,
    InvalidUsernameError,
    InvalidUserRoleError,
)
from warehouse_control_center.domain.validation import PASSWORD_MAX_LENGTH, validate_username

_GENERIC_AUTHENTICATION_MESSAGE = "Invalid username or password."
_DUMMY_PASSWORD = "not-the-provided-password"


class AuthenticationService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        password_hasher: PasswordHasher,
        clock: Clock,
        *,
        dummy_hash: str | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._password_hasher = password_hasher
        self._clock = clock
        self._dummy_hash = dummy_hash or password_hasher.hash_password(_DUMMY_PASSWORD)
        self._password_changes = PasswordChangeService(uow_factory, password_hasher, clock)

    def login(self, username: str, password: str) -> SessionContext:
        audit_name = _sanitize_attempted_username(username)
        try:
            canonical_username = validate_username(username)
        except InvalidUsernameError:
            canonical_username = None

        candidate_password = password if len(password) <= PASSWORD_MAX_LENGTH else "oversized"
        with self._uow_factory() as uow:
            uow.users.lock_for_administration()
            now = utc_timestamp(self._clock.now())
            invalid_stored_credential = False
            try:
                user = (
                    uow.users.get_by_normalized_username(canonical_username)
                    if canonical_username is not None
                    else None
                )
            except InvalidPasswordError:
                user = None
                invalid_stored_credential = True

            if user is None:
                self._password_hasher.verify_password(self._dummy_hash, candidate_password)
                uow.audits.add(
                    make_audit_event(
                        action=AuditAction.LOGIN_FAILURE,
                        actor_name=audit_name,
                        entity_id=audit_name,
                        timestamp=now,
                        details={
                            "reason": (
                                "stored_credential_invalid"
                                if invalid_stored_credential
                                else "unknown_or_invalid_username"
                            )
                        },
                    )
                )
                uow.commit()
                raise AuthenticationError(_GENERIC_AUTHENTICATION_MESSAGE)

            password_matches = self._password_hasher.verify_password(
                user.password_hash, candidate_password
            )
            if not user.active or user.archived_at is not None:
                uow.audits.add(
                    make_audit_event(
                        action=AuditAction.LOGIN_FAILURE,
                        actor_id=user.id,
                        actor_name=user.username,
                        entity_id=user.id or audit_name,
                        timestamp=now,
                        details={"reason": "unavailable_account"},
                    )
                )
                uow.commit()
                raise AuthenticationError(_GENERIC_AUTHENTICATION_MESSAGE)

            if user.locked_until is not None and user.locked_until > now:
                uow.audits.add(
                    make_audit_event(
                        action=AuditAction.LOGIN_BLOCKED,
                        actor_id=user.id,
                        actor_name=user.username,
                        entity_id=user.id or audit_name,
                        timestamp=now,
                        details={"reason": "temporary_lock"},
                    )
                )
                uow.commit()
                raise AuthenticationError(_GENERIC_AUTHENTICATION_MESSAGE)

            if not password_matches:
                user.failed_login_attempts += 1
                duration = lockout_duration(user.failed_login_attempts)
                user.locked_until = now + duration if duration is not None else None
                user.updated_at = now
                saved = uow.users.save(user)
                uow.audits.add(
                    make_audit_event(
                        action=AuditAction.LOGIN_FAILURE,
                        actor_id=saved.id,
                        actor_name=saved.username,
                        entity_id=saved.id or audit_name,
                        timestamp=now,
                        details={"reason": "credential_mismatch"},
                    )
                )
                uow.commit()
                raise AuthenticationError(_GENERIC_AUTHENTICATION_MESSAGE)

            user.failed_login_attempts = 0
            user.locked_until = None
            user.updated_at = now
            if self._password_hasher.needs_rehash(user.password_hash):
                user.password_hash = self._password_hasher.hash_password(password)
            saved = uow.users.save(user)
            uow.audits.add(
                make_audit_event(
                    action=AuditAction.LOGIN_SUCCESS,
                    actor_id=saved.id,
                    actor_name=saved.username,
                    entity_id=saved.id or audit_name,
                    timestamp=now,
                    details={"password_change_required": saved.must_change_password},
                )
            )
            uow.commit()

        if saved.id is None:
            raise RuntimeError("Persisted user is missing an id")
        return SessionContext(
            user_id=saved.id,
            username=saved.username,
            role=saved.role,
            authenticated_at=now,
            must_change_password=saved.must_change_password,
            credential_version=saved.credential_version,
        )

    def change_password(
        self,
        session: SessionContext,
        current_password: str,
        new_password: str,
    ) -> SessionContext:
        return self._password_changes.change_password(session, current_password, new_password)

    def logout(self, session: SessionContext) -> None:
        now = utc_timestamp(self._clock.now())
        with self._uow_factory() as uow:
            try:
                actor = uow.users.get_by_id(session.user_id)
            except (InvalidPasswordError, InvalidUserRoleError):
                actor = None
            uow.audits.add(
                make_audit_event(
                    action=AuditAction.LOGOUT,
                    actor_id=actor.id if actor is not None else None,
                    actor_name=(
                        actor.username
                        if actor is not None
                        else _sanitize_attempted_username(session.username)
                    ),
                    entity_id=session.user_id,
                    timestamp=now,
                )
            )
            uow.commit()


def _sanitize_attempted_username(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    sanitized = "".join(
        character for character in normalized if not unicodedata.category(character).startswith("C")
    )
    return sanitized[:64] or "<empty>"
