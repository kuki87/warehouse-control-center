"""Purpose-specific persistence ports used by application services."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from warehouse_control_center.domain.entities import (
    AuditEvent,
    Client,
    Courier,
    Shipment,
    ShipmentProblem,
    ShipmentSmsEvent,
    ShipmentSmsSummary,
    ShipmentStatusHistory,
    ShipmentWeightCheck,
    User,
)
from warehouse_control_center.domain.enums import (
    ShipmentStatus,
    SmsMessageType,
    SmsSenderType,
    SmsSendStatus,
)

ShipmentSortField = Literal[
    "shipment_number",
    "recipient_name",
    "recipient_city",
    "status",
    "received_at",
    "updated_at",
]
SortDirection = Literal["asc", "desc"]


@dataclass(frozen=True, slots=True)
class ShipmentListQuery:
    offset: int
    limit: int
    search: str | None = None
    status: ShipmentStatus | None = None
    courier_id: int | None = None
    city: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    include_archived: bool = False
    problem_only: bool = False
    sort_by: ShipmentSortField = "received_at"
    sort_direction: SortDirection = "desc"


@dataclass(frozen=True, slots=True)
class SmsEventListQuery:
    shipment_id: int
    offset: int
    limit: int
    sender_type: SmsSenderType | None = None
    message_type: SmsMessageType | None = None
    send_status: SmsSendStatus | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class ShipmentSmsListQuery:
    offset: int
    limit: int
    search: str | None = None
    sender_type: SmsSenderType | None = None
    message_type: SmsMessageType | None = None
    send_status: SmsSendStatus | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class UserRepository(Protocol):
    def add(self, user: User) -> User: ...

    def save(self, user: User) -> User: ...

    def get_by_id(self, user_id: int) -> User | None: ...

    def get_by_normalized_username(self, username: str) -> User | None: ...

    def list_users(
        self,
        *,
        search: str | None = None,
        include_archived: bool = False,
    ) -> list[User]: ...

    def count_users(self) -> int: ...

    def count_active_admins(self) -> int: ...

    def lock_for_administration(self) -> None: ...


class CourierRepository(Protocol):
    def add(self, courier: Courier) -> Courier: ...

    def get_by_id(self, courier_id: int) -> Courier | None: ...

    def get_by_normalized_code(self, courier_code: str) -> Courier | None: ...


class ClientRepository(Protocol):
    def add(self, client: Client) -> Client: ...

    def save(self, client: Client) -> Client: ...

    def get_by_id(self, client_id: int) -> Client | None: ...

    def get_by_normalized_code(self, client_code: str) -> Client | None: ...

    def list_clients(self, *, search: str | None, active_only: bool) -> list[Client]: ...


class ShipmentRepository(Protocol):
    def add(self, shipment: Shipment) -> Shipment: ...

    def get_by_id(self, shipment_id: int) -> Shipment | None: ...

    def get_by_normalized_shipment_number(self, shipment_number: str) -> Shipment | None: ...

    def save(self, shipment: Shipment) -> Shipment: ...

    def list_page(self, query: ShipmentListQuery) -> tuple[list[Shipment], int]: ...

    def add_history(self, history: ShipmentStatusHistory) -> ShipmentStatusHistory: ...

    def list_history(self, shipment_id: int) -> list[ShipmentStatusHistory]: ...

    def add_problem(self, problem: ShipmentProblem) -> ShipmentProblem: ...

    def save_problem(self, problem: ShipmentProblem) -> ShipmentProblem: ...

    def get_open_problem(self, shipment_id: int) -> ShipmentProblem | None: ...

    def add_weight_check(self, check: ShipmentWeightCheck) -> ShipmentWeightCheck: ...

    def list_weight_checks(self, shipment_id: int) -> list[ShipmentWeightCheck]: ...


class ShipmentNumberRepository(Protocol):
    """Allocate visible shipment numbers without exposing sequence persistence."""

    def allocate(self) -> str: ...


class ShipmentSmsRepository(Protocol):
    """Append-only SMS persistence; update and delete are intentionally absent."""

    def add(self, event: ShipmentSmsEvent) -> ShipmentSmsEvent: ...

    def list_for_shipment(self, query: SmsEventListQuery) -> tuple[list[ShipmentSmsEvent], int]: ...

    def list_shipments(
        self, query: ShipmentSmsListQuery
    ) -> tuple[list[ShipmentSmsSummary], int]: ...


class AuditRepository(Protocol):
    """Append-only audit persistence; update and delete are intentionally absent."""

    def add(self, event: AuditEvent) -> AuditEvent: ...

    def get_by_id(self, event_id: int) -> AuditEvent | None: ...
