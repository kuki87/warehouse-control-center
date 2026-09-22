"""Create the Phase 1 operational schema.

Revision ID: 0001_phase1
Revises:
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_phase1"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("username_normalized", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "failed_login_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "failed_login_attempts >= 0", name="ck_users_failed_login_attempts_nonnegative"
        ),
        sa.CheckConstraint(
            "role IN ('ADMIN', 'WAREHOUSE_OPERATOR', 'SUPERVISOR')",
            name="ck_users_role_valid",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username_normalized", name="uq_users_username_normalized"),
    )

    op.create_table(
        "couriers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("courier_code", sa.String(length=100), nullable=False),
        sa.Column("courier_code_normalized", sa.String(length=100), nullable=False),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("last_name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=100), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_couriers"),
        sa.UniqueConstraint("courier_code_normalized", name="uq_couriers_courier_code_normalized"),
    )

    op.create_table(
        "shipments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracking_number", sa.String(length=255), nullable=False),
        sa.Column("tracking_number_normalized", sa.String(length=255), nullable=False),
        sa.Column("barcode", sa.String(length=255), nullable=False),
        sa.Column("barcode_normalized", sa.String(length=255), nullable=False),
        sa.Column("recipient_name", sa.String(length=255), nullable=False),
        sa.Column("recipient_address", sa.String(length=500), nullable=False),
        sa.Column("recipient_city", sa.String(length=255), nullable=False),
        sa.Column("recipient_phone", sa.String(length=100), nullable=False),
        sa.Column("sender_name", sa.String(length=255), nullable=False),
        sa.Column("courier_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="RECEIVED", nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sorted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "status IN ('RECEIVED', 'SORTING', 'READY_FOR_COURIER', 'ASSIGNED', "
            "'DISPATCHED', 'RETURNED', 'PROBLEM')",
            name="ck_shipments_status_valid",
        ),
        sa.CheckConstraint("version >= 1", name="ck_shipments_version_positive"),
        sa.ForeignKeyConstraint(
            ["courier_id"],
            ["couriers.id"],
            name="fk_shipments_courier_id_couriers",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_shipments_created_by_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shipments"),
        sa.UniqueConstraint("barcode_normalized", name="uq_shipments_barcode_normalized"),
        sa.UniqueConstraint(
            "tracking_number_normalized", name="uq_shipments_tracking_number_normalized"
        ),
    )
    op.create_index("ix_shipments_status", "shipments", ["status"], unique=False)
    op.create_index(
        "ix_shipments_courier_id_status", "shipments", ["courier_id", "status"], unique=False
    )
    op.create_index("ix_shipments_received_at", "shipments", ["received_at"], unique=False)
    op.create_index(
        "ix_shipments_status_received_at", "shipments", ["status", "received_at"], unique=False
    )
    op.create_index("ix_shipments_recipient_city", "shipments", ["recipient_city"], unique=False)

    op.create_table(
        "shipment_status_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("old_status", sa.String(length=32), nullable=False),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("changed_by", sa.Integer(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("is_admin_override", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "old_status IN ('RECEIVED', 'SORTING', 'READY_FOR_COURIER', 'ASSIGNED', "
            "'DISPATCHED', 'RETURNED', 'PROBLEM')",
            name="ck_shipment_status_history_old_status_valid",
        ),
        sa.CheckConstraint(
            "new_status IN ('RECEIVED', 'SORTING', 'READY_FOR_COURIER', 'ASSIGNED', "
            "'DISPATCHED', 'RETURNED', 'PROBLEM')",
            name="ck_shipment_status_history_new_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name="fk_shipment_status_history_changed_by_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name="fk_shipment_status_history_shipment_id_shipments",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shipment_status_history"),
    )
    op.create_index(
        "ix_shipment_status_history_shipment_timestamp",
        "shipment_status_history",
        ["shipment_id", "timestamp"],
        unique=False,
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=100), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_audit_events_actor_id_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_timestamp", "audit_events", ["timestamp"], unique=False)
    op.create_index(
        "ix_audit_events_entity_type_entity_id",
        "audit_events",
        ["entity_type", "entity_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_entity_type_entity_id", table_name="audit_events")
    op.drop_index("ix_audit_events_timestamp", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(
        "ix_shipment_status_history_shipment_timestamp",
        table_name="shipment_status_history",
    )
    op.drop_table("shipment_status_history")
    op.drop_index("ix_shipments_recipient_city", table_name="shipments")
    op.drop_index("ix_shipments_status_received_at", table_name="shipments")
    op.drop_index("ix_shipments_received_at", table_name="shipments")
    op.drop_index("ix_shipments_courier_id_status", table_name="shipments")
    op.drop_index("ix_shipments_status", table_name="shipments")
    op.drop_table("shipments")
    op.drop_table("couriers")
    op.drop_table("users")
