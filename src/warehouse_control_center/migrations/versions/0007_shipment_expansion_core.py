"""Add contract clients, shipment measurements, and control weighing.

Revision ID: 0007_shipment_expansion_core
Revises: 0006_unify_shipment_identifier
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_shipment_expansion_core"
down_revision: str | None = "0006_unify_shipment_identifier"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MAX_INTEGER = 2_147_483_647


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_code", sa.String(length=64), nullable=False),
        sa.Column("client_code_normalized", sa.String(length=64), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("tax_id", sa.String(length=64), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("city", sa.String(length=255), nullable=False),
        sa.Column("contact_name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=100), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("contract_number", sa.String(length=100), nullable=True),
        sa.Column("contract_start", sa.Date(), nullable=True),
        sa.Column("contract_end", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "length(trim(client_code)) BETWEEN 1 AND 64", name="ck_clients_client_code_length"
        ),
        sa.CheckConstraint(
            "length(trim(company_name)) BETWEEN 1 AND 255", name="ck_clients_company_name_length"
        ),
        sa.CheckConstraint(
            "length(trim(address)) BETWEEN 1 AND 500", name="ck_clients_address_length"
        ),
        sa.CheckConstraint("length(trim(city)) BETWEEN 1 AND 255", name="ck_clients_city_length"),
        sa.CheckConstraint("active IN (0, 1)", name="ck_clients_active_boolean"),
        sa.CheckConstraint(
            "contract_start IS NULL OR contract_end IS NULL OR contract_end >= contract_start",
            name="ck_clients_contract_dates_ordered",
        ),
        sa.CheckConstraint(
            "notes IS NULL OR length(notes) <= 4000", name="ck_clients_notes_length"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_clients"),
        sa.UniqueConstraint("client_code_normalized", name="uq_clients_client_code_normalized"),
    )
    op.create_index("ix_clients_company_name", "clients", ["company_name"])
    op.create_index("ix_clients_city", "clients", ["city"])
    op.create_index("ix_clients_active", "clients", ["active"])

    with op.batch_alter_table("shipments", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("sender_client_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("package_count", sa.Integer(), server_default=sa.text("1"), nullable=False)
        )
        batch_op.add_column(sa.Column("length_mm", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("width_mm", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("height_mm", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("declared_weight_g", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_shipments_sender_client_id_clients",
            "clients",
            ["sender_client_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint("package_count_positive", "package_count >= 1")
        for column in ("length_mm", "width_mm", "height_mm"):
            batch_op.create_check_constraint(
                f"{column}_positive",
                f"{column} IS NULL OR {column} BETWEEN 1 AND {_MAX_INTEGER}",
            )
        batch_op.create_check_constraint(
            "declared_weight_g_positive",
            f"declared_weight_g IS NULL OR declared_weight_g BETWEEN 1 AND {_MAX_INTEGER}",
        )
    op.create_index("ix_shipments_sender_client_id", "shipments", ["sender_client_id"])

    op.create_table(
        "shipment_weight_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("declared_weight_g_snapshot", sa.Integer(), nullable=False),
        sa.Column("measured_weight_g", sa.Integer(), nullable=False),
        sa.Column("absolute_difference_g", sa.Integer(), nullable=False),
        sa.Column("difference_percent", sa.Numeric(precision=9, scale=4), nullable=True),
        sa.Column("tolerance_abs_g_snapshot", sa.Integer(), nullable=False),
        sa.Column("tolerance_percent_snapshot", sa.Numeric(precision=9, scale=4), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("checked_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "declared_weight_g_snapshot > 0",
            name="ck_shipment_weight_checks_declared_weight_positive",
        ),
        sa.CheckConstraint(
            "measured_weight_g > 0", name="ck_shipment_weight_checks_measured_weight_positive"
        ),
        sa.CheckConstraint(
            "absolute_difference_g >= 0", name="ck_shipment_weight_checks_difference_nonnegative"
        ),
        sa.CheckConstraint(
            "tolerance_abs_g_snapshot >= 0", name="ck_shipment_weight_checks_tolerance_nonnegative"
        ),
        sa.CheckConstraint(
            "result IN ('MATCH', 'UNDER_TOLERANCE', 'OVER_TOLERANCE')",
            name="ck_shipment_weight_checks_result_valid",
        ),
        sa.CheckConstraint("length(note) <= 2000", name="ck_shipment_weight_checks_note_length"),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name="fk_shipment_weight_checks_shipment_id_shipments",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["checked_by_user_id"],
            ["users.id"],
            name="fk_shipment_weight_checks_checked_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shipment_weight_checks"),
    )
    op.create_index(
        "ix_weight_checks_shipment_checked",
        "shipment_weight_checks",
        ["shipment_id", "checked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_weight_checks_shipment_checked", table_name="shipment_weight_checks")
    op.drop_table("shipment_weight_checks")
    op.drop_index("ix_shipments_sender_client_id", table_name="shipments")
    with op.batch_alter_table("shipments", recreate="always") as batch_op:
        batch_op.drop_constraint(op.f("ck_shipments_declared_weight_g_positive"), type_="check")
        for column in ("height_mm", "width_mm", "length_mm"):
            batch_op.drop_constraint(op.f(f"ck_shipments_{column}_positive"), type_="check")
        batch_op.drop_constraint(op.f("ck_shipments_package_count_positive"), type_="check")
        batch_op.drop_constraint(op.f("fk_shipments_sender_client_id_clients"), type_="foreignkey")
        for column in (
            "declared_weight_g",
            "height_mm",
            "width_mm",
            "length_mm",
            "package_count",
            "sender_client_id",
        ):
            batch_op.drop_column(column)
    op.drop_index("ix_clients_active", table_name="clients")
    op.drop_index("ix_clients_city", table_name="clients")
    op.drop_index("ix_clients_company_name", table_name="clients")
    op.drop_table("clients")
