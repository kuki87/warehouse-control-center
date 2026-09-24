"""Persistence-independent business entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from warehouse_control_center.domain.client_validation import validate_client_fields
from warehouse_control_center.domain.enums import (
    ProblemType,
    ShipmentStatus,
    UserRole,
    WeightCheckResult,
)
from warehouse_control_center.domain.measurements import (
    validate_dimension_cm,
    validate_package_count,
    validate_weight_g,
)
from warehouse_control_center.domain.normalization import (
    normalize_client_code,
    normalize_courier_code,
    normalize_shipment_number,
    normalize_username,
)
from warehouse_control_center.domain.shipment_validation import validate_shipment_fields
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
class Client:
    client_code: str
    company_name: str
    address: str
    city: str
    client_code_normalized: str = ""
    tax_id: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    contract_number: str | None = None
    contract_start: date | None = None
    contract_end: date | None = None
    active: bool = True
    notes: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    id: int | None = None

    def __post_init__(self) -> None:
        validated = validate_client_fields(
            client_code=self.client_code,
            company_name=self.company_name,
            tax_id=self.tax_id,
            address=self.address,
            city=self.city,
            contact_name=self.contact_name,
            phone=self.phone,
            email=self.email,
            contract_number=self.contract_number,
            contract_start=self.contract_start,
            contract_end=self.contract_end,
            notes=self.notes,
        )
        for name in validated.__dataclass_fields__:
            setattr(self, name, getattr(validated, name))
        self.client_code_normalized = normalize_client_code(self.client_code)


@dataclass(slots=True)
class Shipment:
    shipment_number: str
    recipient_name: str
    recipient_address: str
    recipient_city: str
    recipient_phone: str
    sender_name: str
    created_by: int
    shipment_number_normalized: str = ""
    sender_client_id: int | None = None
    package_count: int = 1
    length_cm: Decimal | None = None
    width_cm: Decimal | None = None
    height_cm: Decimal | None = None
    declared_weight_g: int | None = None
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
        validated = validate_shipment_fields(
            shipment_number=self.shipment_number,
            recipient_name=self.recipient_name,
            recipient_address=self.recipient_address,
            recipient_city=self.recipient_city,
            recipient_phone=self.recipient_phone,
            sender_name=self.sender_name,
            notes=self.notes,
        )
        self.shipment_number = validated.shipment_number
        self.recipient_name = validated.recipient_name
        self.recipient_address = validated.recipient_address
        self.recipient_city = validated.recipient_city
        self.recipient_phone = validated.recipient_phone
        self.sender_name = validated.sender_name
        self.notes = validated.notes
        self.package_count = validate_package_count(self.package_count)
        self.length_cm = validate_dimension_cm("Length", self.length_cm)
        self.width_cm = validate_dimension_cm("Width", self.width_cm)
        self.height_cm = validate_dimension_cm("Height", self.height_cm)
        self.declared_weight_g = validate_weight_g(
            "Declared weight", self.declared_weight_g, required=False
        )
        if not isinstance(self.status, ShipmentStatus):
            raise ValueError("Unsupported shipment status")
        if self.version < 1:
            raise ValueError("Shipment version must be positive")
        self.shipment_number_normalized = normalize_shipment_number(self.shipment_number)


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
class ShipmentProblem:
    shipment_id: int
    problem_type: ProblemType
    previous_status: ShipmentStatus
    reported_by: int
    reported_at: datetime = field(default_factory=utc_now)
    description: str | None = None
    resolved_by: int | None = None
    resolved_at: datetime | None = None
    id: int | None = None


@dataclass(slots=True)
class ShipmentWeightCheck:
    shipment_id: int
    declared_weight_g_snapshot: int
    measured_weight_g: int
    absolute_difference_g: int
    tolerance_abs_g_snapshot: int
    result: WeightCheckResult
    checked_by_user_id: int
    checked_at: datetime = field(default_factory=utc_now)
    difference_percent: Decimal | None = None
    tolerance_percent_snapshot: Decimal | None = None
    note: str | None = None
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
