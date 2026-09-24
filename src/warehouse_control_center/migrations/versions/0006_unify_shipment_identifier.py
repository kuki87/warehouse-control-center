"""Unify shipment tracking and barcode values into one canonical identifier.

Revision ID: 0006_unify_shipment_identifier
Revises: 0005_automatic_shipment_numbering
Create Date: 2026-09-24

The physical ``tracking_number`` column names are intentionally retained.  Renaming
them would force an additional SQLite table rewrite without changing the data
contract.  Application and domain code expose these columns only as
``shipment_number``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_unify_shipment_identifier"
down_revision: str | None = "0005_automatic_shipment_numbering"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    inconsistent = connection.exec_driver_sql(
        "SELECT COUNT(*) FROM shipments WHERE "
        "tracking_number IS NULL OR tracking_number_normalized IS NULL OR "
        "barcode IS NULL OR barcode_normalized IS NULL OR "
        "tracking_number != barcode OR "
        "tracking_number_normalized != barcode_normalized"
    ).scalar_one()
    if inconsistent:
        raise RuntimeError(
            "Cannot unify shipment identifiers: existing tracking and barcode values disagree"
        )

    with op.batch_alter_table("shipments", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_shipments_barcode_normalized", type_="unique")
        batch_op.drop_constraint(op.f("ck_shipments_barcode_normalized_length"), type_="check")
        batch_op.drop_constraint(op.f("ck_shipments_barcode_length"), type_="check")
        batch_op.drop_constraint(
            op.f("ck_shipments_tracking_number_normalized_length"), type_="check"
        )
        batch_op.drop_constraint(op.f("ck_shipments_tracking_number_length"), type_="check")
        batch_op.drop_column("barcode_normalized")
        batch_op.drop_column("barcode")
        batch_op.create_check_constraint(
            "shipment_number_length",
            "length(trim(tracking_number)) >= 1 AND length(tracking_number) <= 255",
        )
        batch_op.create_check_constraint(
            "shipment_number_normalized_length",
            "length(trim(tracking_number_normalized)) >= 1 "
            "AND length(tracking_number_normalized) <= 255",
        )


def downgrade() -> None:
    op.add_column("shipments", sa.Column("barcode", sa.String(length=255), nullable=True))
    op.add_column(
        "shipments",
        sa.Column("barcode_normalized", sa.String(length=255), nullable=True),
    )
    connection = op.get_bind()
    connection.exec_driver_sql(
        "UPDATE shipments SET barcode = tracking_number, "
        "barcode_normalized = tracking_number_normalized"
    )

    with op.batch_alter_table("shipments", recreate="always") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_shipments_shipment_number_normalized_length"), type_="check"
        )
        batch_op.drop_constraint(op.f("ck_shipments_shipment_number_length"), type_="check")
        batch_op.alter_column("barcode", existing_type=sa.String(length=255), nullable=False)
        batch_op.alter_column(
            "barcode_normalized", existing_type=sa.String(length=255), nullable=False
        )
        batch_op.create_unique_constraint("uq_shipments_barcode_normalized", ["barcode_normalized"])
        batch_op.create_check_constraint(
            "tracking_number_length",
            "length(trim(tracking_number)) >= 1 AND length(tracking_number) <= 255",
        )
        batch_op.create_check_constraint(
            "tracking_number_normalized_length",
            "length(trim(tracking_number_normalized)) >= 1 "
            "AND length(tracking_number_normalized) <= 255",
        )
        batch_op.create_check_constraint(
            "barcode_length", "length(trim(barcode)) >= 1 AND length(barcode) <= 255"
        )
        batch_op.create_check_constraint(
            "barcode_normalized_length",
            "length(trim(barcode_normalized)) >= 1 AND length(barcode_normalized) <= 255",
        )
