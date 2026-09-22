"""Centralized Phase 2 username, password, and stored-hash policy."""

import base64
import binascii
import re
import unicodedata

from warehouse_control_center.domain.enums import UserRole
from warehouse_control_center.domain.exceptions import (
    InvalidPasswordError,
    InvalidUsernameError,
    InvalidUserRoleError,
)

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 64
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 1024
TEMPORARY_PASSWORD_LENGTH = 24
PASSWORD_HASH_MAX_LENGTH = 255
ARGON2_MAX_MEMORY_COST_KIB = 262_144
ARGON2_MAX_TIME_COST = 10
ARGON2_MAX_PARALLELISM = 16
ARGON2_MAX_HASH_LENGTH = 64

_ALLOWED_USERNAME_PUNCTUATION = frozenset("._-")
_ARGON2ID_PATTERN = re.compile(
    r"\$argon2id\$v=19\$m=(?P<memory>[1-9][0-9]*),"
    r"t=(?P<time>[1-9][0-9]*),p=(?P<parallelism>[1-9][0-9]*)\$"
    r"(?P<salt>[A-Za-z0-9+/]{8,})\$(?P<hash>[A-Za-z0-9+/]{8,})"
)


def validate_username(value: str) -> str:
    """Return an NFKC/trimmed username containing letters, numbers, dot, dash, or underscore."""
    canonical = unicodedata.normalize("NFKC", value).strip()
    if not USERNAME_MIN_LENGTH <= len(canonical) <= USERNAME_MAX_LENGTH:
        raise InvalidUsernameError(
            f"Username must be between {USERNAME_MIN_LENGTH} and {USERNAME_MAX_LENGTH} characters"
        )
    for character in canonical:
        category = unicodedata.category(character)
        if category.startswith("C"):
            raise InvalidUsernameError("Username must not contain control characters")
        if not (category.startswith(("L", "N")) or character in _ALLOWED_USERNAME_PUNCTUATION):
            raise InvalidUsernameError(
                "Username may contain only letters, numbers, dot, dash, and underscore"
            )
    return canonical


def validate_password(value: str) -> None:
    """Apply a length-only modern policy without altering the supplied password."""
    if not value or not value.strip():
        raise InvalidPasswordError("Password must not be empty or whitespace-only")
    if len(value) < PASSWORD_MIN_LENGTH:
        raise InvalidPasswordError(
            f"Password must contain at least {PASSWORD_MIN_LENGTH} characters"
        )
    if len(value) > PASSWORD_MAX_LENGTH:
        raise InvalidPasswordError(
            f"Password must contain at most {PASSWORD_MAX_LENGTH} characters"
        )


def validate_password_hash(value: str) -> None:
    """Reject malformed or resource-abusive Argon2id encodings before verification."""
    if len(value) > PASSWORD_HASH_MAX_LENGTH:
        raise InvalidPasswordError("Password hash must use the Argon2id format")
    match = _ARGON2ID_PATTERN.fullmatch(value)
    if match is None:
        raise InvalidPasswordError("Password hash must use the Argon2id format")
    memory = int(match["memory"])
    time = int(match["time"])
    parallelism = int(match["parallelism"])
    if (
        memory < 8 * parallelism
        or memory > ARGON2_MAX_MEMORY_COST_KIB
        or time > ARGON2_MAX_TIME_COST
        or parallelism > ARGON2_MAX_PARALLELISM
    ):
        raise InvalidPasswordError("Password hash parameters exceed supported safety limits")
    salt = _decode_argon2_base64(match["salt"])
    digest = _decode_argon2_base64(match["hash"])
    if len(salt) < 8 or not 16 <= len(digest) <= ARGON2_MAX_HASH_LENGTH:
        raise InvalidPasswordError("Password hash has invalid salt or digest length")


def validate_user_role(value: object) -> UserRole:
    if not isinstance(value, UserRole):
        raise InvalidUserRoleError("Unsupported user role")
    return value


def _decode_argon2_base64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding, validate=True)
    except (binascii.Error, ValueError) as error:
        raise InvalidPasswordError("Password hash contains invalid encoding") from error
