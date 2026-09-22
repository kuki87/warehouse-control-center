"""Security ports implemented by audited infrastructure adapters."""

from typing import Protocol


class PasswordHasher(Protocol):
    def hash_password(self, password: str) -> str: ...

    def verify_password(self, password_hash: str, password: str) -> bool: ...

    def needs_rehash(self, password_hash: str) -> bool: ...


class TemporaryPasswordGenerator(Protocol):
    def generate(self) -> str: ...
