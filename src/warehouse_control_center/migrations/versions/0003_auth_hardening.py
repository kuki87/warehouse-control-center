"""Harden stored credentials and user-state invariants.

Revision ID: 0003_auth_hardening
Revises: 0002_authentication
Create Date: 2026-09-21
"""

import base64
import binascii
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_auth_hardening"
down_revision: str | None = "0002_authentication"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HASH_PATTERN = re.compile(
    r"\$argon2id\$v=19\$m=(?P<memory>[1-9][0-9]*),"
    r"t=(?P<time>[1-9][0-9]*),p=(?P<parallelism>[1-9][0-9]*)\$"
    r"(?P<salt>[A-Za-z0-9+/]{8,})\$(?P<hash>[A-Za-z0-9+/]{8,})"
)


def upgrade() -> None:
    connection = op.get_bind()
    stored_hashes = connection.exec_driver_sql("SELECT id, password_hash FROM users").all()
    invalid_ids = [user_id for user_id, value in stored_hashes if not _supported_hash(value)]
    if invalid_ids:
        raise RuntimeError(
            "Cannot apply authentication hardening: "
            f"{len(invalid_ids)} stored credential(s) are not supported Argon2id encodings"
        )
    invalid_state_count = connection.exec_driver_sql(
        "SELECT COUNT(*) FROM users "
        "WHERE username_normalized != trim(username_normalized) "
        "OR must_change_password NOT IN (0, 1) "
        "OR active NOT IN (0, 1)"
    ).scalar_one()
    if invalid_state_count:
        raise RuntimeError(
            "Cannot apply authentication hardening: "
            f"{invalid_state_count} user record(s) violate Phase 2 state invariants"
        )

    with op.batch_alter_table("users", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column(
                "credential_version",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch_op.drop_constraint(op.f("ck_users_password_hash_argon2id"), type_="check")
        batch_op.create_check_constraint(
            "password_hash_argon2id",
            "password_hash GLOB '$argon2id$v=19$m=*,t=*,p=*$*$*'",
        )
        batch_op.create_check_constraint(
            "username_normalized_trimmed",
            "username_normalized = trim(username_normalized)",
        )
        batch_op.create_check_constraint(
            "must_change_password_boolean", "must_change_password IN (0, 1)"
        )
        batch_op.create_check_constraint("active_boolean", "active IN (0, 1)")
        batch_op.create_check_constraint(
            "credential_version_nonnegative", "credential_version >= 0"
        )


def downgrade() -> None:
    with op.batch_alter_table("users", recreate="always") as batch_op:
        batch_op.drop_constraint(op.f("ck_users_credential_version_nonnegative"), type_="check")
        batch_op.drop_constraint(op.f("ck_users_active_boolean"), type_="check")
        batch_op.drop_constraint(op.f("ck_users_must_change_password_boolean"), type_="check")
        batch_op.drop_constraint(op.f("ck_users_username_normalized_trimmed"), type_="check")
        batch_op.drop_constraint(op.f("ck_users_password_hash_argon2id"), type_="check")
        batch_op.create_check_constraint(
            "password_hash_argon2id", "password_hash GLOB '$argon2id$*'"
        )
        batch_op.drop_column("credential_version")


def _supported_hash(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 255:
        return False
    match = _HASH_PATTERN.fullmatch(value)
    if match is None:
        return False
    memory = int(match["memory"])
    time = int(match["time"])
    parallelism = int(match["parallelism"])
    if memory < 8 * parallelism or memory > 262_144 or time > 10 or parallelism > 16:
        return False
    try:
        salt = _decode(match["salt"])
        digest = _decode(match["hash"])
    except (binascii.Error, ValueError):
        return False
    return len(salt) >= 8 and 16 <= len(digest) <= 64


def _decode(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), validate=True)
