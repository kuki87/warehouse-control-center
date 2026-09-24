"""Phase 1 SQLAlchemy mappings; never expose these models to the UI."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from warehouse_control_center.domain.client_validation import (
    CLIENT_ADDRESS_MAX_LENGTH,
    CLIENT_CITY_MAX_LENGTH,
    CLIENT_CODE_MAX_LENGTH,
    CLIENT_EMAIL_MAX_LENGTH,
    CLIENT_NOTES_MAX_LENGTH,
    CLIENT_PHONE_MAX_LENGTH,
    COMPANY_NAME_MAX_LENGTH,
    CONTACT_NAME_MAX_LENGTH,
    CONTRACT_NUMBER_MAX_LENGTH,
    TAX_ID_MAX_LENGTH,
)
from warehouse_control_center.domain.enums import (
    ProblemType,
    ShipmentStatus,
    UserRole,
    WeightCheckResult,
)
from warehouse_control_center.domain.measurements import MAX_STORED_MEASUREMENT
from warehouse_control_center.domain.shipment_numbering import (
    SHIPMENT_NUMBER_EXHAUSTED_VALUE,
)
from warehouse_control_center.domain.shipment_validation import (
    NOTES_MAX_LENGTH,
    PROBLEM_DESCRIPTION_MAX_LENGTH,
    RECIPIENT_ADDRESS_MAX_LENGTH,
    RECIPIENT_CITY_MAX_LENGTH,
    RECIPIENT_NAME_MAX_LENGTH,
    RECIPIENT_PHONE_MAX_LENGTH,
    RECIPIENT_PHONE_MIN_LENGTH,
    SENDER_NAME_MAX_LENGTH,
    SHIPMENT_NUMBER_MAX_LENGTH,
    STATUS_REASON_MAX_LENGTH,
)
from warehouse_control_center.infrastructure.database.base import Base, UTCDateTime, utc_now


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


def _allowed_values(column: str, enum_class: type[StrEnum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in enum_class)
    return f"{column} IN ({values})"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class UserModel(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("failed_login_attempts >= 0", name="failed_login_attempts_nonnegative"),
        CheckConstraint("credential_version >= 0", name="credential_version_nonnegative"),
        CheckConstraint(_allowed_values("role", UserRole), name="role_valid"),
        CheckConstraint("length(username) BETWEEN 3 AND 64", name="username_length"),
        CheckConstraint(
            "length(username_normalized) BETWEEN 3 AND 64",
            name="username_normalized_length",
        ),
        CheckConstraint(
            "username_normalized = trim(username_normalized)",
            name="username_normalized_trimmed",
        ),
        CheckConstraint("username = trim(username)", name="username_trimmed"),
        CheckConstraint(
            "password_hash GLOB '$argon2id$v=19$m=*,t=*,p=*$*$*'",
            name="password_hash_argon2id",
        ),
        CheckConstraint("length(password_hash) <= 255", name="password_hash_length"),
        CheckConstraint("must_change_password IN (0, 1)", name="must_change_password_boolean"),
        CheckConstraint("active IN (0, 1)", name="active_boolean"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    username_normalized: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SqlEnum(
            UserRole,
            length=32,
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0"), nullable=False
    )
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("1"), nullable=False
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    credential_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class CourierModel(TimestampMixin, Base):
    __tablename__ = "couriers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    courier_code: Mapped[str] = mapped_column(String(100), nullable=False)
    courier_code_normalized: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("1"), nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ClientModel(TimestampMixin, Base):
    __tablename__ = "clients"
    __table_args__ = (
        CheckConstraint(
            f"length(trim(client_code)) BETWEEN 1 AND {CLIENT_CODE_MAX_LENGTH}",
            name="client_code_length",
        ),
        CheckConstraint(
            f"length(trim(company_name)) BETWEEN 1 AND {COMPANY_NAME_MAX_LENGTH}",
            name="company_name_length",
        ),
        CheckConstraint(
            f"length(trim(address)) BETWEEN 1 AND {CLIENT_ADDRESS_MAX_LENGTH}",
            name="address_length",
        ),
        CheckConstraint(
            f"length(trim(city)) BETWEEN 1 AND {CLIENT_CITY_MAX_LENGTH}",
            name="city_length",
        ),
        CheckConstraint("active IN (0, 1)", name="active_boolean"),
        CheckConstraint(
            "contract_start IS NULL OR contract_end IS NULL OR contract_end >= contract_start",
            name="contract_dates_ordered",
        ),
        CheckConstraint(
            f"notes IS NULL OR length(notes) <= {CLIENT_NOTES_MAX_LENGTH}",
            name="notes_length",
        ),
        Index("ix_clients_company_name", "company_name"),
        Index("ix_clients_city", "city"),
        Index("ix_clients_active", "active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_code: Mapped[str] = mapped_column(String(CLIENT_CODE_MAX_LENGTH), nullable=False)
    client_code_normalized: Mapped[str] = mapped_column(
        String(CLIENT_CODE_MAX_LENGTH), nullable=False, unique=True
    )
    company_name: Mapped[str] = mapped_column(String(COMPANY_NAME_MAX_LENGTH), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(TAX_ID_MAX_LENGTH), nullable=True)
    address: Mapped[str] = mapped_column(String(CLIENT_ADDRESS_MAX_LENGTH), nullable=False)
    city: Mapped[str] = mapped_column(String(CLIENT_CITY_MAX_LENGTH), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(CONTACT_NAME_MAX_LENGTH))
    phone: Mapped[str | None] = mapped_column(String(CLIENT_PHONE_MAX_LENGTH))
    email: Mapped[str | None] = mapped_column(String(CLIENT_EMAIL_MAX_LENGTH))
    contract_number: Mapped[str | None] = mapped_column(String(CONTRACT_NUMBER_MAX_LENGTH))
    contract_start: Mapped[date | None] = mapped_column(Date())
    contract_end: Mapped[date | None] = mapped_column(Date())
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ShipmentNumberSequenceModel(Base):
    __tablename__ = "shipment_number_sequences"
    __table_args__ = (
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 64", name="name_length"),
        CheckConstraint(
            f"next_value BETWEEN 1 AND {SHIPMENT_NUMBER_EXHAUSTED_VALUE}",
            name="next_value_range",
        ),
    )

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_value: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
        nullable=False,
    )


class ShipmentModel(TimestampMixin, Base):
    __tablename__ = "shipments"
    __table_args__ = (
        CheckConstraint(_allowed_values("status", ShipmentStatus), name="status_valid"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("package_count >= 1", name="package_count_positive"),
        CheckConstraint(
            f"length_mm IS NULL OR length_mm BETWEEN 1 AND {MAX_STORED_MEASUREMENT}",
            name="length_mm_positive",
        ),
        CheckConstraint(
            f"width_mm IS NULL OR width_mm BETWEEN 1 AND {MAX_STORED_MEASUREMENT}",
            name="width_mm_positive",
        ),
        CheckConstraint(
            f"height_mm IS NULL OR height_mm BETWEEN 1 AND {MAX_STORED_MEASUREMENT}",
            name="height_mm_positive",
        ),
        CheckConstraint(
            "declared_weight_g IS NULL OR declared_weight_g BETWEEN 1 AND "
            f"{MAX_STORED_MEASUREMENT}",
            name="declared_weight_g_positive",
        ),
        CheckConstraint(
            f"length(trim(tracking_number)) >= 1 AND "
            f"length(tracking_number) <= {SHIPMENT_NUMBER_MAX_LENGTH}",
            name="shipment_number_length",
        ),
        CheckConstraint(
            "length(trim(tracking_number_normalized)) >= 1 AND "
            f"length(tracking_number_normalized) <= {SHIPMENT_NUMBER_MAX_LENGTH}",
            name="shipment_number_normalized_length",
        ),
        CheckConstraint(
            f"length(trim(recipient_name)) >= 1 AND "
            f"length(recipient_name) <= {RECIPIENT_NAME_MAX_LENGTH}",
            name="recipient_name_length",
        ),
        CheckConstraint(
            f"length(trim(recipient_address)) >= 1 AND "
            f"length(recipient_address) <= {RECIPIENT_ADDRESS_MAX_LENGTH}",
            name="recipient_address_length",
        ),
        CheckConstraint(
            f"length(trim(recipient_city)) >= 1 AND "
            f"length(recipient_city) <= {RECIPIENT_CITY_MAX_LENGTH}",
            name="recipient_city_length",
        ),
        CheckConstraint(
            f"length(trim(recipient_phone)) >= {RECIPIENT_PHONE_MIN_LENGTH} AND "
            f"length(recipient_phone) <= {RECIPIENT_PHONE_MAX_LENGTH}",
            name="recipient_phone_length",
        ),
        CheckConstraint(
            f"length(trim(sender_name)) >= 1 AND length(sender_name) <= {SENDER_NAME_MAX_LENGTH}",
            name="sender_name_length",
        ),
        CheckConstraint(
            f"notes IS NULL OR length(notes) <= {NOTES_MAX_LENGTH}",
            name="notes_length",
        ),
        Index("ix_shipments_status", "status"),
        Index("ix_shipments_courier_id_status", "courier_id", "status"),
        Index("ix_shipments_received_at", "received_at"),
        Index("ix_shipments_status_received_at", "status", "received_at"),
        Index("ix_shipments_recipient_city", "recipient_city"),
        Index("ix_shipments_updated_at", "updated_at"),
        Index("ix_shipments_sender_client_id", "sender_client_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The physical column names are retained through Phase 3D to avoid a risky SQLite
    # table-wide identifier rename.  The ORM and every layer above it expose only the
    # canonical shipment-number terminology.
    shipment_number: Mapped[str] = mapped_column("tracking_number", String(255), nullable=False)
    shipment_number_normalized: Mapped[str] = mapped_column(
        "tracking_number_normalized", String(255), nullable=False, unique=True
    )
    recipient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_address: Mapped[str] = mapped_column(String(500), nullable=False)
    recipient_city: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String(100), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), nullable=True
    )
    package_count: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    length_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    declared_weight_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    courier_id: Mapped[int | None] = mapped_column(
        ForeignKey("couriers.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[ShipmentStatus] = mapped_column(
        SqlEnum(
            ShipmentStatus,
            length=32,
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
        ),
        default=ShipmentStatus.RECEIVED,
        server_default=ShipmentStatus.RECEIVED.value,
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    sorted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )

    __mapper_args__ = {"version_id_col": version}


class ShipmentStatusHistoryModel(Base):
    __tablename__ = "shipment_status_history"
    __table_args__ = (
        CheckConstraint(_allowed_values("old_status", ShipmentStatus), name="old_status_valid"),
        CheckConstraint(_allowed_values("new_status", ShipmentStatus), name="new_status_valid"),
        CheckConstraint("old_status != new_status", name="status_changed"),
        CheckConstraint("is_admin_override IN (0, 1)", name="admin_override_boolean"),
        CheckConstraint(
            "is_admin_override = 0 OR length(trim(reason)) BETWEEN 1 AND "
            f"{STATUS_REASON_MAX_LENGTH}",
            name="override_reason_required",
        ),
        CheckConstraint(
            f"reason IS NULL OR length(reason) <= {STATUS_REASON_MAX_LENGTH}",
            name="reason_length",
        ),
        Index("ix_shipment_status_history_shipment_timestamp", "shipment_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT"), nullable=False
    )
    old_status: Mapped[ShipmentStatus] = mapped_column(
        SqlEnum(
            ShipmentStatus,
            length=32,
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    new_status: Mapped[ShipmentStatus] = mapped_column(
        SqlEnum(
            ShipmentStatus,
            length=32,
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    changed_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_admin_override: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0"), nullable=False
    )


class ShipmentProblemModel(Base):
    __tablename__ = "shipment_problems"
    __table_args__ = (
        CheckConstraint(_allowed_values("problem_type", ProblemType), name="problem_type_valid"),
        CheckConstraint(
            _allowed_values("previous_status", ShipmentStatus), name="previous_status_valid"
        ),
        CheckConstraint(
            f"description IS NULL OR length(description) <= {PROBLEM_DESCRIPTION_MAX_LENGTH}",
            name="description_length",
        ),
        CheckConstraint(
            "(problem_type != 'OTHER') OR "
            "(description IS NOT NULL AND length(trim(description)) > 0)",
            name="other_description_required",
        ),
        CheckConstraint(
            "(resolved_at IS NULL AND resolved_by IS NULL) OR "
            "(resolved_at IS NOT NULL AND resolved_by IS NOT NULL "
            "AND resolved_at >= reported_at)",
            name="resolution_consistent",
        ),
        Index("ix_shipment_problems_shipment_reported", "shipment_id", "reported_at"),
        Index(
            "uq_shipment_problems_one_open",
            "shipment_id",
            unique=True,
            sqlite_where=text("resolved_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT"), nullable=False
    )
    problem_type: Mapped[ProblemType] = mapped_column(
        SqlEnum(
            ProblemType,
            length=32,
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_status: Mapped[ShipmentStatus] = mapped_column(
        SqlEnum(
            ShipmentStatus,
            length=32,
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    reported_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reported_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ShipmentWeightCheckModel(Base):
    __tablename__ = "shipment_weight_checks"
    __table_args__ = (
        CheckConstraint("declared_weight_g_snapshot > 0", name="declared_weight_positive"),
        CheckConstraint("measured_weight_g > 0", name="measured_weight_positive"),
        CheckConstraint("absolute_difference_g >= 0", name="difference_nonnegative"),
        CheckConstraint("tolerance_abs_g_snapshot >= 0", name="tolerance_nonnegative"),
        CheckConstraint(_allowed_values("result", WeightCheckResult), name="result_valid"),
        CheckConstraint("length(note) <= 2000", name="note_length"),
        Index("ix_weight_checks_shipment_checked", "shipment_id", "checked_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT"), nullable=False
    )
    declared_weight_g_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    measured_weight_g: Mapped[int] = mapped_column(Integer, nullable=False)
    absolute_difference_g: Mapped[int] = mapped_column(Integer, nullable=False)
    difference_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    tolerance_abs_g_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    tolerance_percent_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    result: Mapped[WeightCheckResult] = mapped_column(
        SqlEnum(
            WeightCheckResult,
            length=32,
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    checked_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEventModel(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_timestamp", "timestamp"),
        Index("ix_audit_events_entity_type_entity_id", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    actor_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    details_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
