"""Add transactional automatic shipment-number allocation.

Revision ID: 0005_automatic_shipment_numbering
Revises: 0004_shipments_domain
Create Date: 2026-09-23
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_automatic_shipment_numbering"
down_revision: str | None = "0004_shipments_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEQUENCE_NAME = "shipment_number"
_GENERATED_IDENTIFIER = re.compile(r"^E([0-9]{9})$")
_EXHAUSTED_SENTINEL = 1_000_000_000


def upgrade() -> None:
    connection = op.get_bind()
    highest_compatible = 0
    rows = connection.exec_driver_sql("SELECT tracking_number, barcode FROM shipments")
    for tracking_number, barcode in rows:
        for identifier in (tracking_number, barcode):
            if not isinstance(identifier, str):
                continue
            match = _GENERATED_IDENTIFIER.fullmatch(identifier)
            if match is not None:
                highest_compatible = max(highest_compatible, int(match.group(1)))

    op.create_table(
        "shipment_number_sequences",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("next_value", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 64",
            name="ck_shipment_number_sequences_name_length",
        ),
        sa.CheckConstraint(
            f"next_value BETWEEN 1 AND {_EXHAUSTED_SENTINEL}",
            name="ck_shipment_number_sequences_next_value_range",
        ),
        sa.PrimaryKeyConstraint("name", name="pk_shipment_number_sequences"),
    )
    connection.execute(
        sa.text(
            "INSERT INTO shipment_number_sequences (name, next_value) VALUES (:name, :next_value)"
        ),
        {
            "name": _SEQUENCE_NAME,
            "next_value": highest_compatible + 1,
        },
    )


def downgrade() -> None:
    op.drop_table("shipment_number_sequences")
