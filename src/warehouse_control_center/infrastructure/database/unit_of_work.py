"""SQLAlchemy transaction boundary with explicit commit semantics."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session

from warehouse_control_center.application.ports.repositories import (
    AuditRepository,
    ClientRepository,
    CourierRepository,
    ShipmentNumberRepository,
    ShipmentRepository,
    ShipmentSmsRepository,
    UserRepository,
)
from warehouse_control_center.infrastructure.database.engine import SessionFactory
from warehouse_control_center.infrastructure.database.repositories import (
    SqlAlchemyAuditRepository,
    SqlAlchemyClientRepository,
    SqlAlchemyCourierRepository,
    SqlAlchemyShipmentNumberRepository,
    SqlAlchemyShipmentRepository,
    SqlAlchemyShipmentSmsRepository,
    SqlAlchemyUserRepository,
)


class SqlAlchemyUnitOfWork:
    """Own one Session and all repositories participating in its transaction."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._users: UserRepository | None = None
        self._couriers: CourierRepository | None = None
        self._clients: ClientRepository | None = None
        self._shipments: ShipmentRepository | None = None
        self._shipment_numbers: ShipmentNumberRepository | None = None
        self._shipment_sms: ShipmentSmsRepository | None = None
        self._audits: AuditRepository | None = None
        self.closed = True

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Unit of Work is not active")
        return self._session

    @property
    def users(self) -> UserRepository:
        if self._users is None:
            raise RuntimeError("Unit of Work is not active")
        return self._users

    @property
    def couriers(self) -> CourierRepository:
        if self._couriers is None:
            raise RuntimeError("Unit of Work is not active")
        return self._couriers

    @property
    def clients(self) -> ClientRepository:
        if self._clients is None:
            raise RuntimeError("Unit of Work is not active")
        return self._clients

    @property
    def shipments(self) -> ShipmentRepository:
        if self._shipments is None:
            raise RuntimeError("Unit of Work is not active")
        return self._shipments

    @property
    def shipment_numbers(self) -> ShipmentNumberRepository:
        if self._shipment_numbers is None:
            raise RuntimeError("Unit of Work is not active")
        return self._shipment_numbers

    @property
    def shipment_sms(self) -> ShipmentSmsRepository:
        if self._shipment_sms is None:
            raise RuntimeError("Unit of Work is not active")
        return self._shipment_sms

    @property
    def audits(self) -> AuditRepository:
        if self._audits is None:
            raise RuntimeError("Unit of Work is not active")
        return self._audits

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        if self._session is not None:
            raise RuntimeError("Unit of Work cannot be entered more than once")
        self._session = self._session_factory()
        self._users = SqlAlchemyUserRepository(self._session)
        self._couriers = SqlAlchemyCourierRepository(self._session)
        self._clients = SqlAlchemyClientRepository(self._session)
        self._shipments = SqlAlchemyShipmentRepository(self._session)
        self._shipment_numbers = SqlAlchemyShipmentNumberRepository(self._session)
        self._shipment_sms = SqlAlchemyShipmentSmsRepository(self._session)
        self._audits = SqlAlchemyAuditRepository(self._session)
        self.closed = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        try:
            self.rollback()
        finally:
            self.session.close()
            self._session = None
            self._users = None
            self._couriers = None
            self._clients = None
            self._shipments = None
            self._shipment_numbers = None
            self._shipment_sms = None
            self._audits = None
            self.closed = True

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
