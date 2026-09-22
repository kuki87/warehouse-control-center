"""Authorized user administration and safe user-query use cases."""

from collections.abc import Callable

from warehouse_control_center.application.dto import SessionContext, TemporaryCredential, UserDTO
from warehouse_control_center.application.permissions import require_permission
from warehouse_control_center.application.ports.clock import Clock
from warehouse_control_center.application.ports.passwords import (
    PasswordHasher,
    TemporaryPasswordGenerator,
)
from warehouse_control_center.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from warehouse_control_center.application.services._audit import make_audit_event
from warehouse_control_center.application.services._time import utc_timestamp
from warehouse_control_center.application.services.password_change import PasswordChangeService
from warehouse_control_center.domain.entities import User
from warehouse_control_center.domain.enums import AuditAction, Permission, UserRole
from warehouse_control_center.domain.exceptions import (
    InvalidPasswordError,
    InvalidUserRoleError,
    InvalidUserStateError,
    LastActiveAdministratorError,
    PermissionDeniedError,
    UserNotFoundError,
)
from warehouse_control_center.domain.normalization import normalize_username
from warehouse_control_center.domain.validation import (
    validate_password,
    validate_user_role,
    validate_username,
)


class UserService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        password_hasher: PasswordHasher,
        password_generator: TemporaryPasswordGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._password_hasher = password_hasher
        self._password_generator = password_generator
        self._clock = clock
        self._password_changes = PasswordChangeService(uow_factory, password_hasher, clock)

    def create_user(
        self, session: SessionContext, username: str, role: UserRole
    ) -> TemporaryCredential:
        require_permission(session, Permission.MANAGE_USERS)
        canonical_username = validate_username(username)
        validated_role = validate_user_role(role)
        with self._uow_factory() as uow:
            uow.users.lock_for_administration()
            actor = _require_current_administrator(uow, session)
            temporary_password = self._password_generator.generate()
            validate_password(temporary_password)
            now = utc_timestamp(self._clock.now())
            user = uow.users.add(
                User(
                    username=canonical_username,
                    password_hash=self._password_hasher.hash_password(temporary_password),
                    role=validated_role,
                    active=True,
                    must_change_password=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            uow.audits.add(
                make_audit_event(
                    action=AuditAction.USER_CREATED,
                    actor_id=actor.id,
                    actor_name=actor.username,
                    entity_id=user.id or canonical_username,
                    timestamp=now,
                    details={"role": validated_role.value, "username": user.username},
                )
            )
            uow.commit()
        return TemporaryCredential(UserDTO.from_entity(user), temporary_password)

    def get_user(self, session: SessionContext, user_id: int) -> UserDTO:
        require_permission(session, Permission.MANAGE_USERS)
        with self._uow_factory() as uow:
            _require_current_administrator(uow, session)
            return UserDTO.from_entity(_get_user(uow.users.get_by_id, user_id))

    def list_users(
        self,
        session: SessionContext,
        *,
        search: str | None = None,
        include_archived: bool = False,
    ) -> list[UserDTO]:
        require_permission(session, Permission.MANAGE_USERS)
        with self._uow_factory() as uow:
            _require_current_administrator(uow, session)
            return [
                UserDTO.from_entity(user)
                for user in uow.users.list_users(
                    search=search,
                    include_archived=include_archived,
                )
            ]

    def change_username(self, session: SessionContext, user_id: int, username: str) -> UserDTO:
        canonical_username = validate_username(username)
        return self._mutate_user(
            session,
            user_id,
            AuditAction.USER_RENAMED,
            lambda user: _rename(user, canonical_username),
            details={"username": canonical_username},
        )

    def change_role(self, session: SessionContext, user_id: int, role: UserRole) -> UserDTO:
        validated_role = validate_user_role(role)

        def mutate(user: User) -> None:
            if user.role == validated_role:
                raise InvalidUserStateError("User already has that role")
            user.role = validated_role

        return self._mutate_user(
            session,
            user_id,
            AuditAction.USER_ROLE_CHANGED,
            mutate,
            removes_active_admin=lambda user: (
                user.role is UserRole.ADMIN and validated_role is not UserRole.ADMIN
            ),
            details={"role": validated_role.value},
        )

    def activate_user(self, session: SessionContext, user_id: int) -> UserDTO:
        def mutate(user: User) -> None:
            if user.archived_at is not None:
                raise InvalidUserStateError("Archived user must be restored before activation")
            if user.active:
                raise InvalidUserStateError("User is already active")
            user.active = True

        return self._mutate_user(session, user_id, AuditAction.USER_ACTIVATED, mutate)

    def deactivate_user(self, session: SessionContext, user_id: int) -> UserDTO:
        def mutate(user: User) -> None:
            if not user.active:
                raise InvalidUserStateError("User is already inactive")
            user.active = False

        return self._mutate_user(
            session,
            user_id,
            AuditAction.USER_DEACTIVATED,
            mutate,
            removes_active_admin=lambda user: user.role is UserRole.ADMIN,
        )

    def archive_user(self, session: SessionContext, user_id: int) -> UserDTO:
        now = utc_timestamp(self._clock.now())

        def mutate(user: User) -> None:
            if user.archived_at is not None:
                raise InvalidUserStateError("User is already archived")
            user.active = False
            user.archived_at = now

        return self._mutate_user(
            session,
            user_id,
            AuditAction.USER_ARCHIVED,
            mutate,
            removes_active_admin=lambda user: user.role is UserRole.ADMIN and user.active,
        )

    def restore_user(self, session: SessionContext, user_id: int) -> UserDTO:
        def mutate(user: User) -> None:
            if user.archived_at is None:
                raise InvalidUserStateError("User is not archived")
            user.archived_at = None
            user.active = False

        return self._mutate_user(session, user_id, AuditAction.USER_RESTORED, mutate)

    def reset_password(self, session: SessionContext, user_id: int) -> TemporaryCredential:
        require_permission(session, Permission.MANAGE_USERS)
        if user_id == session.user_id:
            raise InvalidUserStateError("Use change_password to change your own password")
        with self._uow_factory() as uow:
            uow.users.lock_for_administration()
            actor = _require_current_administrator(uow, session)
            temporary_password = self._password_generator.generate()
            validate_password(temporary_password)
            now = utc_timestamp(self._clock.now())
            user = _get_user(uow.users.get_by_id, user_id)
            if user.archived_at is not None:
                raise InvalidUserStateError("Cannot reset an archived user's password")
            user.password_hash = self._password_hasher.hash_password(temporary_password)
            user.credential_version += 1
            user.must_change_password = True
            user.failed_login_attempts = 0
            user.locked_until = None
            user.updated_at = now
            saved = uow.users.save(user)
            uow.audits.add(
                make_audit_event(
                    action=AuditAction.PASSWORD_RESET,
                    actor_id=actor.id,
                    actor_name=actor.username,
                    entity_id=saved.id or user_id,
                    timestamp=now,
                )
            )
            uow.commit()
        return TemporaryCredential(UserDTO.from_entity(saved), temporary_password)

    def change_password(
        self,
        session: SessionContext,
        current_password: str,
        new_password: str,
    ) -> SessionContext:
        return self._password_changes.change_password(session, current_password, new_password)

    def _mutate_user(
        self,
        session: SessionContext,
        user_id: int,
        action: AuditAction,
        mutation: Callable[[User], None],
        *,
        removes_active_admin: Callable[[User], bool] | None = None,
        details: dict[str, object] | None = None,
    ) -> UserDTO:
        require_permission(session, Permission.MANAGE_USERS)
        with self._uow_factory() as uow:
            uow.users.lock_for_administration()
            actor = _require_current_administrator(uow, session)
            now = utc_timestamp(self._clock.now())
            user = _get_user(uow.users.get_by_id, user_id)
            if (
                removes_active_admin is not None
                and user.active
                and user.archived_at is None
                and removes_active_admin(user)
                and uow.users.count_active_admins() <= 1
            ):
                raise LastActiveAdministratorError(
                    "Operation would remove the last active administrator"
                )
            mutation(user)
            user.updated_at = now
            saved = uow.users.save(user)
            uow.audits.add(
                make_audit_event(
                    action=action,
                    actor_id=actor.id,
                    actor_name=actor.username,
                    entity_id=saved.id or user_id,
                    timestamp=now,
                    details=details,
                )
            )
            uow.commit()
        return UserDTO.from_entity(saved)


def _get_user(getter: Callable[[int], User | None], user_id: int) -> User:
    user = getter(user_id)
    if user is None:
        raise UserNotFoundError(f"User {user_id} does not exist")
    return user


def _require_current_administrator(uow: UnitOfWork, session: SessionContext) -> User:
    try:
        actor = uow.users.get_by_id(session.user_id)
    except (InvalidPasswordError, InvalidUserRoleError):
        raise PermissionDeniedError("Current session is no longer authorized") from None
    if (
        actor is None
        or not actor.active
        or actor.archived_at is not None
        or actor.role is not UserRole.ADMIN
        or actor.credential_version != session.credential_version
    ):
        raise PermissionDeniedError("Current session is no longer authorized")
    return actor


def _rename(user: User, username: str) -> None:
    if user.username == username:
        raise InvalidUserStateError("User already has that username")
    user.username = username
    user.username_normalized = normalize_username(username)
