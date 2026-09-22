"""Persistence-independent Phase 1 entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from warehouse_control_center.domain.enums import ShipmentStatus, UserRole
from warehouse_control_center.domain.normalization import (
    normalize_barcode,
    normalize_courier_code,
    normalize_tracking_number,
    normalize_username,
)
from warehouse_control_center.domain.validation import (
    validate_password_hash,
    validate_user_role,
    validate_username,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class User:
    username: str
    password_hash: str = field(repr=False)
    role: UserRole
    username_normalized: str = ""
    must_change_password: bool = False
    active: bool = True
    failed_login_attempts: int = 0
    credential_version: int = 0
    locked_until: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    archived_at: datetime | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        self.username = validate_username(self.username)
        validate_password_hash(self.password_hash)
        self.role = validate_user_role(self.role)
        if self.credential_version < 0:
            raise ValueError("Credential version must not be negative")
        self.username_normalized = normalize_username(self.username)


@dataclass(slots=True)
class Courier:
    courier_code: str
    first_name: str
    last_name: str
    phone: str | None = None
    courier_code_normalized: str = ""
    active: bool = True
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    archived_at: datetime | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        self.courier_code_normalized = normalize_courier_code(self.courier_code)


@dataclass(slots=True)
class Shipment:
    tracking_number: str
    barcode: str
    recipient_name: str
    recipient_address: str
    recipient_city: str
    recipient_phone: str
    sender_name: str
    created_by: int
    tracking_number_normalized: str = ""
    barcode_normalized: str = ""
    courier_id: int | None = None
    status: ShipmentStatus = ShipmentStatus.RECEIVED
    received_at: datetime = field(default_factory=utc_now)
    sorted_at: datetime | None = None
    assigned_at: datetime | None = None
    dispatched_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    notes: str | None = None
    archived_at: datetime | None = None
    version: int = 1
    id: int | None = None

    def __post_init__(self) -> None:
        self.tracking_number_normalized = normalize_tracking_number(self.tracking_number)
        self.barcode_normalized = normalize_barcode(self.barcode)


@dataclass(slots=True)
class ShipmentStatusHistory:
    shipment_id: int
    old_status: ShipmentStatus
    new_status: ShipmentStatus
    changed_by: int
    timestamp: datetime = field(default_factory=utc_now)
    reason: str | None = None
    is_admin_override: bool = False
    id: int | None = None


@dataclass(slots=True)
class AuditEvent:
    actor_name_snapshot: str
    action: str
    entity_type: str
    entity_id: str
    details: dict[str, object] = field(default_factory=dict)
    actor_id: int | None = None
    timestamp: datetime = field(default_factory=utc_now)
    id: int | None = None
