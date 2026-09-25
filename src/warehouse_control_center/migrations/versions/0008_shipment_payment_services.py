"""Add exact payment data and shipment additional services.

Revision ID: 0008_shipment_payment_services
Revises: 0007_shipment_expansion_core
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_shipment_payment_services"
down_revision: str | None = "0007_shipment_expansion_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MAX_MONEY_FEN = 2_147_483_647


def upgrade() -> None:
    with op.batch_alter_table("shipments", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("declared_value_fen", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("cod_enabled", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )
        batch_op.add_column(sa.Column("cod_amount_fen", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("payer", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("payment_method", sa.String(length=16), nullable=True))
        batch_op.create_check_constraint(
            "declared_value_fen_nonnegative",
            f"declared_value_fen IS NULL OR declared_value_fen BETWEEN 0 AND {_MAX_MONEY_FEN}",
        )
        batch_op.create_check_constraint("cod_enabled_boolean", "cod_enabled IN (0, 1)")
        batch_op.create_check_constraint(
            "cod_state_valid",
            "(cod_enabled = 0 AND cod_amount_fen IS NULL) OR "
            f"(cod_enabled = 1 AND cod_amount_fen BETWEEN 1 AND {_MAX_MONEY_FEN})",
        )
        batch_op.create_check_constraint(
            "payer_valid", "payer IS NULL OR payer IN ('SENDER', 'RECIPIENT')"
        )
        batch_op.create_check_constraint(
            "payment_method_valid",
            "payment_method IS NULL OR payment_method IN ('CASH', 'INVOICE', 'ACCOUNT')",
        )

    op.create_table(
        "shipment_services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("service_type", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "service_type IN ('EXPRESS', 'INSURANCE', 'RETURN_DOCUMENTS', 'SATURDAY_DELIVERY')",
            name="ck_shipment_services_service_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name="fk_shipment_services_shipment_id_shipments",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shipment_services"),
        sa.UniqueConstraint("shipment_id", "service_type", name="uq_shipment_services_type"),
    )
    op.create_index("ix_shipment_services_shipment_id", "shipment_services", ["shipment_id"])


def downgrade() -> None:
    op.drop_index("ix_shipment_services_shipment_id", table_name="shipment_services")
    op.drop_table("shipment_services")
    with op.batch_alter_table("shipments", recreate="always") as batch_op:
        batch_op.drop_constraint(op.f("ck_shipments_payment_method_valid"), type_="check")
        batch_op.drop_constraint(op.f("ck_shipments_payer_valid"), type_="check")
        batch_op.drop_constraint(op.f("ck_shipments_cod_state_valid"), type_="check")
        batch_op.drop_constraint(op.f("ck_shipments_cod_enabled_boolean"), type_="check")
        batch_op.drop_constraint(op.f("ck_shipments_declared_value_fen_nonnegative"), type_="check")
        for column in (
            "payment_method",
            "payer",
            "cod_amount_fen",
            "cod_enabled",
            "declared_value_fen",
        ):
            batch_op.drop_column(column)
