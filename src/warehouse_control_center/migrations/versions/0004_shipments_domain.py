"""Add shipment-domain invariants and unresolved problem records.

Revision ID: 0004_shipments_domain
Revises: 0003_auth_hardening
Create Date: 2026-09-22
"""

import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import RowMapping

revision: str = "0004_shipments_domain"
down_revision: str | None = "0003_auth_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PHONE_PUNCTUATION = frozenset("+()-./ ")
_REQUIRED_TEXT_FIELDS = (
    ("tracking_number", 255),
    ("tracking_number_normalized", 255),
    ("barcode", 255),
    ("barcode_normalized", 255),
    ("recipient_name", 255),
    ("recipient_address", 500),
    ("recipient_city", 255),
    ("sender_name", 255),
)


def upgrade() -> None:
    connection = op.get_bind()
    invalid_shipments = sum(
        not _valid_legacy_shipment(row)
        for row in connection.exec_driver_sql(
            "SELECT tracking_number, tracking_number_normalized, barcode, "
            "barcode_normalized, recipient_name, recipient_address, recipient_city, "
            "recipient_phone, sender_name, notes FROM shipments"
        ).mappings()
    )
    invalid_history = connection.exec_driver_sql(
        "SELECT COUNT(*) FROM shipment_status_history WHERE "
        "old_status = new_status OR is_admin_override NOT IN (0, 1) OR "
        "(reason IS NOT NULL AND length(reason) > 1000) OR "
        "(is_admin_override = 1 AND "
        "(reason IS NULL OR length(trim(reason)) NOT BETWEEN 1 AND 1000))"
    ).scalar_one()
    if invalid_shipments or invalid_history:
        raise RuntimeError(
            "Cannot apply shipment-domain constraints: existing shipment data is invalid"
        )

    with op.batch_alter_table("shipments", recreate="always") as batch_op:
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
        batch_op.create_check_constraint(
            "recipient_name_length",
            "length(trim(recipient_name)) >= 1 AND length(recipient_name) <= 255",
        )
        batch_op.create_check_constraint(
            "recipient_address_length",
            "length(trim(recipient_address)) >= 1 AND length(recipient_address) <= 500",
        )
        batch_op.create_check_constraint(
            "recipient_city_length",
            "length(trim(recipient_city)) >= 1 AND length(recipient_city) <= 255",
        )
        batch_op.create_check_constraint(
            "recipient_phone_length",
            "length(trim(recipient_phone)) >= 3 AND length(recipient_phone) <= 100",
        )
        batch_op.create_check_constraint(
            "sender_name_length",
            "length(trim(sender_name)) >= 1 AND length(sender_name) <= 255",
        )
        batch_op.create_check_constraint("notes_length", "notes IS NULL OR length(notes) <= 4000")
    op.create_index("ix_shipments_updated_at", "shipments", ["updated_at"], unique=False)

    with op.batch_alter_table("shipment_status_history", recreate="always") as batch_op:
        batch_op.create_check_constraint("status_changed", "old_status != new_status")
        batch_op.create_check_constraint("admin_override_boolean", "is_admin_override IN (0, 1)")
        batch_op.create_check_constraint(
            "override_reason_required",
            "is_admin_override = 0 OR length(trim(reason)) BETWEEN 1 AND 1000",
        )
        batch_op.create_check_constraint(
            "reason_length", "reason IS NULL OR length(reason) <= 1000"
        )

    op.create_table(
        "shipment_problems",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("problem_type", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("previous_status", sa.String(length=32), nullable=False),
        sa.Column("reported_by", sa.Integer(), nullable=False),
        sa.Column(
            "reported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "problem_type IN ('DAMAGED', 'WRONG_ADDRESS', 'MISSING_DATA', 'NOT_FOUND', 'OTHER')",
            name="ck_shipment_problems_problem_type_valid",
        ),
        sa.CheckConstraint(
            "previous_status IN ('RECEIVED', 'SORTING', 'READY_FOR_COURIER', "
            "'ASSIGNED', 'DISPATCHED', 'RETURNED', 'PROBLEM')",
            name="ck_shipment_problems_previous_status_valid",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(description) <= 2000",
            name="ck_shipment_problems_description_length",
        ),
        sa.CheckConstraint(
            "(problem_type != 'OTHER') OR "
            "(description IS NOT NULL AND length(trim(description)) > 0)",
            name="ck_shipment_problems_other_description_required",
        ),
        sa.CheckConstraint(
            "(resolved_at IS NULL AND resolved_by IS NULL) OR "
            "(resolved_at IS NOT NULL AND resolved_by IS NOT NULL "
            "AND resolved_at >= reported_at)",
            name="ck_shipment_problems_resolution_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name="fk_shipment_problems_shipment_id_shipments",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reported_by"],
            ["users.id"],
            name="fk_shipment_problems_reported_by_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"],
            ["users.id"],
            name="fk_shipment_problems_resolved_by_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shipment_problems"),
    )
    op.create_index(
        "ix_shipment_problems_shipment_reported",
        "shipment_problems",
        ["shipment_id", "reported_at"],
        unique=False,
    )
    op.create_index(
        "uq_shipment_problems_one_open",
        "shipment_problems",
        ["shipment_id"],
        unique=True,
        sqlite_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_shipment_problems_one_open", table_name="shipment_problems")
    op.drop_index("ix_shipment_problems_shipment_reported", table_name="shipment_problems")
    op.drop_table("shipment_problems")

    with op.batch_alter_table("shipment_status_history", recreate="always") as batch_op:
        batch_op.drop_constraint(op.f("ck_shipment_status_history_reason_length"), type_="check")
        batch_op.drop_constraint(
            op.f("ck_shipment_status_history_override_reason_required"), type_="check"
        )
        batch_op.drop_constraint(
            op.f("ck_shipment_status_history_admin_override_boolean"), type_="check"
        )
        batch_op.drop_constraint(op.f("ck_shipment_status_history_status_changed"), type_="check")

    op.drop_index("ix_shipments_updated_at", table_name="shipments")
    with op.batch_alter_table("shipments", recreate="always") as batch_op:
        for name in (
            "notes_length",
            "sender_name_length",
            "recipient_phone_length",
            "recipient_city_length",
            "recipient_address_length",
            "recipient_name_length",
            "barcode_normalized_length",
            "barcode_length",
            "tracking_number_normalized_length",
            "tracking_number_length",
        ):
            batch_op.drop_constraint(op.f(f"ck_shipments_{name}"), type_="check")


def _valid_legacy_shipment(row: RowMapping) -> bool:
    for field, maximum in _REQUIRED_TEXT_FIELDS:
        if not _valid_required_text(row[field], maximum):
            return False
    phone_value = row["recipient_phone"]
    phone = _canonical_text(phone_value)
    if (
        phone is None
        or not isinstance(phone_value, str)
        or not 3 <= len(phone) <= 100
        or len(phone_value) > 100
        or any(
            unicodedata.category(character) != "Nd" and character not in _PHONE_PUNCTUATION
            for character in phone
        )
    ):
        return False
    notes = row["notes"]
    if notes is not None and not _valid_optional_text(notes, 4_000, allow_line_breaks=True):
        return False
    tracking = row["tracking_number"]
    barcode = row["barcode"]
    tracking_normalized = row["tracking_number_normalized"]
    barcode_normalized = row["barcode_normalized"]
    return (
        isinstance(tracking_normalized, str)
        and isinstance(barcode_normalized, str)
        and tracking_normalized == _normalize_identifier(tracking)
        and barcode_normalized == _normalize_identifier(barcode)
    )


def _valid_required_text(value: object, maximum: int) -> bool:
    canonical = _canonical_text(value)
    return (
        canonical is not None
        and isinstance(value, str)
        and len(value) <= maximum
        and len(canonical) <= maximum
        and not _contains_disallowed_control(canonical, allow_line_breaks=False)
    )


def _valid_optional_text(value: object, maximum: int, *, allow_line_breaks: bool) -> bool:
    if not isinstance(value, str) or len(value) > maximum:
        return False
    canonical = unicodedata.normalize("NFKC", value).strip()
    return len(canonical) <= maximum and not _contains_disallowed_control(
        canonical, allow_line_breaks=allow_line_breaks
    )


def _canonical_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    canonical = unicodedata.normalize("NFKC", value).strip()
    return canonical or None


def _contains_disallowed_control(value: str, *, allow_line_breaks: bool) -> bool:
    allowed = {"\n", "\r", "\t"} if allow_line_breaks else set()
    return any(
        unicodedata.category(character).startswith("C") and character not in allowed
        for character in value
    )


def _normalize_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return "".join(unicodedata.normalize("NFKC", value).strip().split()).upper()
