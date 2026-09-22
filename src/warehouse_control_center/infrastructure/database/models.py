"""Phase 1 SQLAlchemy mappings; never expose these models to the UI."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from warehouse_control_center.domain.enums import ShipmentStatus, UserRole
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


class ShipmentModel(TimestampMixin, Base):
    __tablename__ = "shipments"
    __table_args__ = (
        CheckConstraint(_allowed_values("status", ShipmentStatus), name="status_valid"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_shipments_status", "status"),
        Index("ix_shipments_courier_id_status", "courier_id", "status"),
        Index("ix_shipments_received_at", "received_at"),
        Index("ix_shipments_status_received_at", "status", "received_at"),
        Index("ix_shipments_recipient_city", "recipient_city"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tracking_number: Mapped[str] = mapped_column(String(255), nullable=False)
    tracking_number_normalized: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    barcode: Mapped[str] = mapped_column(String(255), nullable=False)
    barcode_normalized: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    recipient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_address: Mapped[str] = mapped_column(String(500), nullable=False)
    recipient_city: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String(100), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
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
