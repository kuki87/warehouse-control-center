"""Idempotent, serialized first-run administrator initialization."""

from warehouse_control_center.application.dto import TemporaryCredential, UserDTO
from warehouse_control_center.application.ports.clock import Clock
from warehouse_control_center.application.ports.passwords import (
    PasswordHasher,
    TemporaryPasswordGenerator,
)
from warehouse_control_center.application.ports.unit_of_work import UnitOfWorkFactory
from warehouse_control_center.application.services._audit import make_audit_event
from warehouse_control_center.application.services._time import utc_timestamp
from warehouse_control_center.domain.entities import User
from warehouse_control_center.domain.enums import AuditAction, UserRole
from warehouse_control_center.domain.validation import validate_password


class FirstRunAdministratorService:
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

    def initialize(self) -> TemporaryCredential | None:
        with self._uow_factory() as uow:
            uow.users.lock_for_administration()
            if uow.users.count_users() != 0:
                return None
            now = utc_timestamp(self._clock.now())

            temporary_password = self._password_generator.generate()
            validate_password(temporary_password)
            user = uow.users.add(
                User(
                    username="admin",
                    password_hash=self._password_hasher.hash_password(temporary_password),
                    role=UserRole.ADMIN,
                    active=True,
                    must_change_password=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            uow.audits.add(
                make_audit_event(
                    action=AuditAction.FIRST_ADMIN_CREATED,
                    actor_id=user.id,
                    actor_name=user.username,
                    entity_id=user.id or "admin",
                    timestamp=now,
                )
            )
            uow.commit()
        return TemporaryCredential(UserDTO.from_entity(user), temporary_password)
