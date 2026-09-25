"""Safe application-facing values that never expose persistence or password hashes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, NoReturn, Self

from warehouse_control_center.domain.entities import (
    Client,
    Shipment,
    ShipmentProblem,
    ShipmentSmsEvent,
    ShipmentSmsSummary,
    ShipmentStatusHistory,
    ShipmentWeightCheck,
    User,
)
from warehouse_control_center.domain.enums import (
    AdditionalServiceType,
    PaymentMethod,
    ProblemType,
    ShipmentPayer,
    ShipmentStatus,
    SmsMessageType,
    SmsSenderType,
    SmsSendStatus,
    UserRole,
    WeightCheckResult,
)
from warehouse_control_center.domain.exceptions import TemporaryCredentialConsumedError


@dataclass(frozen=True, slots=True)
class SessionContext:
    user_id: int
    username: str
    role: UserRole
    authenticated_at: datetime
    must_change_password: bool = False
    credential_version: int = 0


@dataclass(frozen=True, slots=True)
class UserDTO:
    id: int
    username: str
    role: UserRole
    active: bool
    must_change_password: bool
    failed_login_attempts: int
    locked_until: datetime | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None

    @classmethod
    def from_entity(cls, user: User) -> UserDTO:
        if user.id is None:
            raise ValueError("Persisted user must have an id")
        return cls(
            id=user.id,
            username=user.username,
            role=user.role,
            active=user.active,
            must_change_password=user.must_change_password,
            failed_login_attempts=user.failed_login_attempts,
            locked_until=user.locked_until,
            created_at=user.created_at,
            updated_at=user.updated_at,
            archived_at=user.archived_at,
        )


@dataclass(frozen=True, slots=True)
class ClientDTO:
    id: int
    client_code: str
    company_name: str
    tax_id: str | None
    address: str
    city: str
    contact_name: str | None
    phone: str | None
    email: str | None
    contract_number: str | None
    contract_start: date | None
    contract_end: date | None
    active: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, client: Client) -> ClientDTO:
        if client.id is None:
            raise ValueError("Persisted client must have an id")
        return cls(
            id=client.id,
            client_code=client.client_code,
            company_name=client.company_name,
            tax_id=client.tax_id,
            address=client.address,
            city=client.city,
            contact_name=client.contact_name,
            phone=client.phone,
            email=client.email,
            contract_number=client.contract_number,
            contract_start=client.contract_start,
            contract_end=client.contract_end,
            active=client.active,
            notes=client.notes,
            created_at=client.created_at,
            updated_at=client.updated_at,
        )


@dataclass(frozen=True, slots=True)
class ShipmentDTO:
    id: int
    shipment_number: str
    recipient_name: str
    recipient_address: str
    recipient_city: str
    recipient_phone: str
    sender_name: str
    sender_client_id: int | None
    package_count: int
    length_cm: Decimal | None
    width_cm: Decimal | None
    height_cm: Decimal | None
    declared_weight_g: int | None
    courier_id: int | None
    status: ShipmentStatus
    received_at: datetime
    sorted_at: datetime | None
    assigned_at: datetime | None
    dispatched_at: datetime | None
    created_at: datetime
    updated_at: datetime
    created_by: int
    notes: str | None
    archived_at: datetime | None
    version: int
    declared_value_fen: int | None = None
    cod_enabled: bool = False
    cod_amount_fen: int | None = None
    payer: ShipmentPayer | None = None
    payment_method: PaymentMethod | None = None
    services: tuple[AdditionalServiceType, ...] = ()

    @classmethod
    def from_entity(cls, shipment: Shipment) -> ShipmentDTO:
        if shipment.id is None:
            raise ValueError("Persisted shipment must have an id")
        return cls(
            id=shipment.id,
            shipment_number=shipment.shipment_number,
            recipient_name=shipment.recipient_name,
            recipient_address=shipment.recipient_address,
            recipient_city=shipment.recipient_city,
            recipient_phone=shipment.recipient_phone,
            sender_name=shipment.sender_name,
            sender_client_id=shipment.sender_client_id,
            package_count=shipment.package_count,
            length_cm=shipment.length_cm,
            width_cm=shipment.width_cm,
            height_cm=shipment.height_cm,
            declared_weight_g=shipment.declared_weight_g,
            declared_value_fen=shipment.declared_value_fen,
            cod_enabled=shipment.cod_enabled,
            cod_amount_fen=shipment.cod_amount_fen,
            payer=shipment.payer,
            payment_method=shipment.payment_method,
            services=tuple(sorted(shipment.services, key=lambda item: item.value)),
            courier_id=shipment.courier_id,
            status=shipment.status,
            received_at=shipment.received_at,
            sorted_at=shipment.sorted_at,
            assigned_at=shipment.assigned_at,
            dispatched_at=shipment.dispatched_at,
            created_at=shipment.created_at,
            updated_at=shipment.updated_at,
            created_by=shipment.created_by,
            notes=shipment.notes,
            archived_at=shipment.archived_at,
            version=shipment.version,
        )


@dataclass(frozen=True, slots=True)
class ShipmentStatusHistoryDTO:
    id: int
    shipment_id: int
    old_status: ShipmentStatus
    new_status: ShipmentStatus
    changed_by: int
    timestamp: datetime
    reason: str | None
    is_admin_override: bool

    @classmethod
    def from_entity(cls, history: ShipmentStatusHistory) -> ShipmentStatusHistoryDTO:
        if history.id is None:
            raise ValueError("Persisted status history must have an id")
        return cls(
            id=history.id,
            shipment_id=history.shipment_id,
            old_status=history.old_status,
            new_status=history.new_status,
            changed_by=history.changed_by,
            timestamp=history.timestamp,
            reason=history.reason,
            is_admin_override=history.is_admin_override,
        )


@dataclass(frozen=True, slots=True)
class ShipmentProblemDTO:
    id: int
    shipment_id: int
    problem_type: ProblemType
    description: str | None
    previous_status: ShipmentStatus
    reported_by: int
    reported_at: datetime
    resolved_by: int | None
    resolved_at: datetime | None

    @classmethod
    def from_entity(cls, problem: ShipmentProblem) -> ShipmentProblemDTO:
        if problem.id is None:
            raise ValueError("Persisted shipment problem must have an id")
        return cls(
            id=problem.id,
            shipment_id=problem.shipment_id,
            problem_type=problem.problem_type,
            description=problem.description,
            previous_status=problem.previous_status,
            reported_by=problem.reported_by,
            reported_at=problem.reported_at,
            resolved_by=problem.resolved_by,
            resolved_at=problem.resolved_at,
        )


@dataclass(frozen=True, slots=True)
class ShipmentWeightCheckDTO:
    id: int
    shipment_id: int
    declared_weight_g_snapshot: int
    measured_weight_g: int
    absolute_difference_g: int
    difference_percent: Decimal | None
    tolerance_abs_g_snapshot: int
    tolerance_percent_snapshot: Decimal | None
    result: WeightCheckResult
    checked_by_user_id: int
    checked_at: datetime
    note: str | None

    @classmethod
    def from_entity(cls, check: ShipmentWeightCheck) -> ShipmentWeightCheckDTO:
        if check.id is None:
            raise ValueError("Persisted weight check must have an id")
        return cls(
            id=check.id,
            shipment_id=check.shipment_id,
            declared_weight_g_snapshot=check.declared_weight_g_snapshot,
            measured_weight_g=check.measured_weight_g,
            absolute_difference_g=check.absolute_difference_g,
            difference_percent=check.difference_percent,
            tolerance_abs_g_snapshot=check.tolerance_abs_g_snapshot,
            tolerance_percent_snapshot=check.tolerance_percent_snapshot,
            result=check.result,
            checked_by_user_id=check.checked_by_user_id,
            checked_at=check.checked_at,
            note=check.note,
        )


@dataclass(frozen=True, slots=True)
class ShipmentPage:
    items: tuple[ShipmentDTO, ...]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True, slots=True)
class ShipmentSmsEventDTO:
    id: int
    shipment_id: int
    sender_type: SmsSenderType
    sent_by_user_id: int | None
    phone_number: str
    message_type: SmsMessageType
    message_text: str
    send_status: SmsSendStatus
    sent_at: datetime
    delivered_at: datetime | None
    provider_message_id: str | None
    error_message: str | None
    created_at: datetime

    @classmethod
    def from_entity(cls, event: ShipmentSmsEvent) -> ShipmentSmsEventDTO:
        if event.id is None:
            raise ValueError("Persisted SMS event must have an id")
        return cls(
            id=event.id,
            shipment_id=event.shipment_id,
            sender_type=event.sender_type,
            sent_by_user_id=event.sent_by_user_id,
            phone_number=event.phone_number,
            message_type=event.message_type,
            message_text=event.message_text,
            send_status=event.send_status,
            sent_at=event.sent_at,
            delivered_at=event.delivered_at,
            provider_message_id=event.provider_message_id,
            error_message=event.error_message,
            created_at=event.created_at,
        )


@dataclass(frozen=True, slots=True)
class ShipmentSmsEventPage:
    items: tuple[ShipmentSmsEventDTO, ...]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True, slots=True)
class ShipmentSmsSummaryDTO:
    shipment: ShipmentDTO
    sms_count: int
    last_event: ShipmentSmsEventDTO

    @classmethod
    def from_entity(cls, summary: ShipmentSmsSummary) -> ShipmentSmsSummaryDTO:
        return cls(
            shipment=ShipmentDTO.from_entity(summary.shipment),
            sms_count=summary.sms_count,
            last_event=ShipmentSmsEventDTO.from_entity(summary.last_event),
        )


@dataclass(frozen=True, slots=True)
class ShipmentSmsSummaryPage:
    items: tuple[ShipmentSmsSummaryDTO, ...]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True, slots=True)
class ShipmentStatusChangeResult:
    shipment: ShipmentDTO
    changed: bool


class TemporaryCredential:
    """One-shot carrier for a generated password; repr and safe serialization omit it."""

    __slots__ = ("_temporary_password", "user")

    def __init__(self, user: UserDTO, temporary_password: str) -> None:
        self.user = user
        self._temporary_password: str | None = temporary_password

    def take_temporary_password(self) -> str:
        password = self._temporary_password
        if password is None:
            raise TemporaryCredentialConsumedError("Temporary password was already retrieved")
        self._temporary_password = None
        return password

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "user": self.user,
            "temporary_password_available": self._temporary_password is not None,
        }

    def __repr__(self) -> str:
        return f"TemporaryCredential(user={self.user!r}, temporary_password=<redacted>)"

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        memo[id(self)] = self
        return self

    def __reduce__(self) -> NoReturn:
        raise TypeError("TemporaryCredential cannot be pickled")
