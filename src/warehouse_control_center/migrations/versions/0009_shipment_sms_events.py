"""Add append-only shipment SMS events.

Revision ID: 0009_shipment_sms_events
Revises: 0008_shipment_payment_services
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_shipment_sms_events"
down_revision: str | None = "0008_shipment_payment_services"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shipment_sms_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("sender_type", sa.String(length=16), nullable=False),
        sa.Column("sent_by_user_id", sa.Integer(), nullable=True),
        sa.Column("phone_number", sa.String(length=100), nullable=False),
        sa.Column("message_type", sa.String(length=32), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("send_status", sa.String(length=16), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sender_type IN ('WAREHOUSE', 'COURIER', 'SYSTEM')",
            name="ck_shipment_sms_events_sender_type_valid",
        ),
        sa.CheckConstraint(
            "(sender_type = 'SYSTEM' AND sent_by_user_id IS NULL) OR "
            "(sender_type IN ('WAREHOUSE', 'COURIER') AND sent_by_user_id IS NOT NULL)",
            name="ck_shipment_sms_events_sender_user_consistent",
        ),
        sa.CheckConstraint(
            "length(trim(phone_number)) BETWEEN 3 AND 100",
            name="ck_shipment_sms_events_phone_length",
        ),
        sa.CheckConstraint(
            "message_type IN ('ARRIVAL_NOTIFICATION', 'COURIER_NOTIFICATION', "
            "'DELIVERY_ATTEMPT', 'READY_FOR_PICKUP', 'ADDRESS_PROBLEM', 'CUSTOM')",
            name="ck_shipment_sms_events_message_type_valid",
        ),
        sa.CheckConstraint(
            "length(trim(message_text)) BETWEEN 1 AND 1000",
            name="ck_shipment_sms_events_message_text_length",
        ),
        sa.CheckConstraint(
            "send_status IN ('RECORDED', 'PENDING', 'SENT', 'FAILED', 'DELIVERED')",
            name="ck_shipment_sms_events_send_status_valid",
        ),
        sa.CheckConstraint(
            "(send_status = 'DELIVERED' AND delivered_at IS NOT NULL "
            "AND delivered_at >= sent_at) OR "
            "(send_status != 'DELIVERED' AND delivered_at IS NULL)",
            name="ck_shipment_sms_events_delivery_state_consistent",
        ),
        sa.CheckConstraint(
            "provider_message_id IS NULL OR length(provider_message_id) <= 255",
            name="ck_shipment_sms_events_provider_message_id_length",
        ),
        sa.CheckConstraint(
            "error_message IS NULL OR length(error_message) <= 1000",
            name="ck_shipment_sms_events_error_message_length",
        ),
        sa.CheckConstraint(
            "send_status != 'FAILED' OR "
            "(error_message IS NOT NULL AND length(trim(error_message)) > 0)",
            name="ck_shipment_sms_events_failed_error_required",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name="fk_shipment_sms_events_shipment_id_shipments",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sent_by_user_id"],
            ["users.id"],
            name="fk_shipment_sms_events_sent_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shipment_sms_events"),
    )
    op.create_index("ix_shipment_sms_events_shipment_id", "shipment_sms_events", ["shipment_id"])
    op.create_index("ix_shipment_sms_events_sent_at", "shipment_sms_events", ["sent_at"])
    op.create_index("ix_shipment_sms_events_sender_type", "shipment_sms_events", ["sender_type"])
    op.create_index("ix_shipment_sms_events_send_status", "shipment_sms_events", ["send_status"])
    op.create_index(
        "ix_shipment_sms_events_shipment_sent",
        "shipment_sms_events",
        ["shipment_id", "sent_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_shipment_sms_events_shipment_sent", table_name="shipment_sms_events")
    op.drop_index("ix_shipment_sms_events_send_status", table_name="shipment_sms_events")
    op.drop_index("ix_shipment_sms_events_sender_type", table_name="shipment_sms_events")
    op.drop_index("ix_shipment_sms_events_sent_at", table_name="shipment_sms_events")
    op.drop_index("ix_shipment_sms_events_shipment_id", table_name="shipment_sms_events")
    op.drop_table("shipment_sms_events")
