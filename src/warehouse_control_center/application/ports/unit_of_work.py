"""Transaction boundary used by future application services."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from warehouse_control_center.application.ports.repositories import (
    AuditRepository,
    ClientRepository,
    CourierRepository,
    ShipmentNumberRepository,
    ShipmentRepository,
    ShipmentSmsRepository,
    UserRepository,
)


class UnitOfWork(Protocol):
    @property
    def users(self) -> UserRepository: ...

    @property
    def couriers(self) -> CourierRepository: ...

    @property
    def clients(self) -> ClientRepository: ...

    @property
    def shipments(self) -> ShipmentRepository: ...

    @property
    def shipment_numbers(self) -> ShipmentNumberRepository: ...

    @property
    def shipment_sms(self) -> ShipmentSmsRepository: ...

    @property
    def audits(self) -> AuditRepository: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


UnitOfWorkFactory = Callable[[], UnitOfWork]
