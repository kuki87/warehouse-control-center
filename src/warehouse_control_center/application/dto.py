"""Safe application-facing values that never expose persistence or password hashes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn, Self

from warehouse_control_center.domain.entities import (
    Shipment,
    ShipmentProblem,
    ShipmentStatusHistory,
    User,
)
from warehouse_control_center.domain.enums import ProblemType, ShipmentStatus, UserRole
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
class ShipmentDTO:
    id: int
    shipment_number: str
    recipient_name: str
    recipient_address: str
    recipient_city: str
    recipient_phone: str
    sender_name: str
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
class ShipmentPage:
    items: tuple[ShipmentDTO, ...]
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
