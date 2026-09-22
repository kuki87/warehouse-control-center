"""Argon2id password hashing and cryptographically secure temporary passwords."""

import secrets
import string

from argon2 import PasswordHasher as Argon2LibraryHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

from warehouse_control_center.domain.exceptions import InvalidPasswordError
from warehouse_control_center.domain.validation import (
    TEMPORARY_PASSWORD_LENGTH,
    validate_password_hash,
)


class Argon2PasswordHasher:
    def __init__(
        self,
        *,
        time_cost: int = 3,
        memory_cost: int = 65_536,
        parallelism: int = 4,
        hash_len: int = 32,
        salt_len: int = 16,
    ) -> None:
        self._hasher = Argon2LibraryHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=hash_len,
            salt_len=salt_len,
            type=Type.ID,
        )

    def hash_password(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify_password(self, password_hash: str, password: str) -> bool:
        try:
            validate_password_hash(password_hash)
            return self._hasher.verify(password_hash, password)
        except (
            InvalidHashError,
            InvalidPasswordError,
            VerificationError,
            VerifyMismatchError,
        ):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            validate_password_hash(password_hash)
            return self._hasher.check_needs_rehash(password_hash)
        except (InvalidHashError, InvalidPasswordError):
            return True


class SecureTemporaryPasswordGenerator:
    _ALPHABET = string.ascii_letters + string.digits + "-_!@"

    def __init__(self, length: int = TEMPORARY_PASSWORD_LENGTH) -> None:
        if length < TEMPORARY_PASSWORD_LENGTH:
            raise ValueError(
                f"Temporary password length must be at least {TEMPORARY_PASSWORD_LENGTH}"
            )
        self._length = length

    def generate(self) -> str:
        return "".join(secrets.choice(self._ALPHABET) for _ in range(self._length))
