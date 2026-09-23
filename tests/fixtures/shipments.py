"""Reusable authenticated shipment-service harness for Phase 3A integration tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from warehouse_control_center.application.dto import SessionContext, ShipmentDTO
from warehouse_control_center.application.services import (
    AuthenticationService,
    FirstRunAdministratorService,
    ShipmentService,
)
from warehouse_control_center.domain.entities import User
from warehouse_control_center.domain.enums import UserRole
from warehouse_control_center.infrastructure.database.engine import SessionFactory
from warehouse_control_center.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from warehouse_control_center.infrastructure.security import (
    Argon2PasswordHasher,
    SecureTemporaryPasswordGenerator,
)

ADMIN_PASSWORD = "changed-admin-password"
OPERATOR_PASSWORD = "operator-password-123"
SUPERVISOR_PASSWORD = "supervisor-password-123"


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, **kwargs: float) -> None:
        self.current += timedelta(**kwargs)


@dataclass(slots=True)
class ShipmentHarness:
    service: ShipmentService
    authentication: AuthenticationService
    admin: SessionContext
    operator: SessionContext
    supervisor: SessionContext
    clock: FakeClock

    def create(
        self,
        *,
        session: SessionContext | None = None,
        recipient_name: str = "Željko Šarić",
        recipient_address: str = "Ćirila i Metodija 10",
        recipient_city: str = "Banja Luka",
        recipient_phone: str = "+387 65 123 456",
        sender_name: str = "Đorđe Čavić",
        notes: str | None = None,
    ) -> ShipmentDTO:
        return self.service.create_shipment(
            session or self.admin,
            recipient_name=recipient_name,
            recipient_address=recipient_address,
            recipient_city=recipient_city,
            recipient_phone=recipient_phone,
            sender_name=sender_name,
            notes=notes,
        )


def build_shipment_harness(session_factory: SessionFactory) -> ShipmentHarness:
    clock = FakeClock()
    hasher = Argon2PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    first_run = FirstRunAdministratorService(
        uow_factory,
        hasher,
        SecureTemporaryPasswordGenerator(),
        clock,
    )
    authentication = AuthenticationService(uow_factory, hasher, clock)
    credential = first_run.initialize()
    assert credential is not None
    temporary_password = credential.take_temporary_password()
    restricted_admin = authentication.login("admin", temporary_password)
    admin = authentication.change_password(restricted_admin, temporary_password, ADMIN_PASSWORD)

    with uow_factory() as uow:
        for username, role, password in (
            ("operator", UserRole.WAREHOUSE_OPERATOR, OPERATOR_PASSWORD),
            ("supervisor", UserRole.SUPERVISOR, SUPERVISOR_PASSWORD),
        ):
            uow.users.add(
                User(
                    username=username,
                    password_hash=hasher.hash_password(password),
                    role=role,
                    created_at=clock.now(),
                    updated_at=clock.now(),
                )
            )
        uow.commit()
    operator = authentication.login("operator", OPERATOR_PASSWORD)
    supervisor = authentication.login("supervisor", SUPERVISOR_PASSWORD)
    return ShipmentHarness(
        ShipmentService(uow_factory, clock),
        authentication,
        admin,
        operator,
        supervisor,
        clock,
    )
