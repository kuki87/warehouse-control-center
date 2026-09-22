"""Add Phase 2 authentication invariants to users.

Revision ID: 0002_authentication
Revises: 0001_phase1
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_authentication"
down_revision: str | None = "0001_phase1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    invalid_count = connection.exec_driver_sql(
        "SELECT COUNT(*) FROM users "
        "WHERE length(username) NOT BETWEEN 3 AND 64 "
        "OR length(username_normalized) NOT BETWEEN 3 AND 64 "
        "OR username != trim(username) "
        "OR password_hash NOT GLOB '$argon2id$*' "
        "OR length(password_hash) > 255"
    ).scalar_one()
    if invalid_count:
        raise RuntimeError(
            "Cannot apply authentication constraints: existing users violate Phase 2 policy"
        )

    with op.batch_alter_table("users", recreate="always") as batch_op:
        batch_op.create_check_constraint("username_length", "length(username) BETWEEN 3 AND 64")
        batch_op.create_check_constraint(
            "username_normalized_length",
            "length(username_normalized) BETWEEN 3 AND 64",
        )
        batch_op.create_check_constraint("username_trimmed", "username = trim(username)")
        batch_op.create_check_constraint(
            "password_hash_argon2id", "password_hash GLOB '$argon2id$*'"
        )
        batch_op.create_check_constraint("password_hash_length", "length(password_hash) <= 255")


def downgrade() -> None:
    with op.batch_alter_table("users", recreate="always") as batch_op:
        batch_op.drop_constraint(op.f("ck_users_password_hash_length"), type_="check")
        batch_op.drop_constraint(op.f("ck_users_password_hash_argon2id"), type_="check")
        batch_op.drop_constraint(op.f("ck_users_username_trimmed"), type_="check")
        batch_op.drop_constraint(op.f("ck_users_username_normalized_length"), type_="check")
        batch_op.drop_constraint(op.f("ck_users_username_length"), type_="check")
