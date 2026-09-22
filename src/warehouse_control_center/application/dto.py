"""Safe application-facing values that never expose persistence or password hashes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn, Self

from warehouse_control_center.domain.entities import User
from warehouse_control_center.domain.enums import UserRole
from warehouse_control_center.domain.exceptions import TemporaryCredentialConsumedError


@dataclass(frozen=True, slots=True)
class SessionContext:
    user_id: int
    username: str
    role: UserRole
    authenticated_at: datetime
    must_change_password: bool = False
    credential_version: int = 0


@dataclass(frozen=True, slots=True)
class UserDTO:
    id: int
    username: str
    role: UserRole
    active: bool
    must_change_password: bool
    failed_login_attempts: int
    locked_until: datetime | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None

    @classmethod
    def from_entity(cls, user: User) -> UserDTO:
        if user.id is None:
            raise ValueError("Persisted user must have an id")
        return cls(
            id=user.id,
            username=user.username,
            role=user.role,
            active=user.active,
            must_change_password=user.must_change_password,
            failed_login_attempts=user.failed_login_attempts,
            locked_until=user.locked_until,
            created_at=user.created_at,
            updated_at=user.updated_at,
            archived_at=user.archived_at,
        )


class TemporaryCredential:
    """One-shot carrier for a generated password; repr and safe serialization omit it."""

    __slots__ = ("_temporary_password", "user")

    def __init__(self, user: UserDTO, temporary_password: str) -> None:
        self.user = user
        self._temporary_password: str | None = temporary_password

    def take_temporary_password(self) -> str:
        password = self._temporary_password
        if password is None:
            raise TemporaryCredentialConsumedError("Temporary password was already retrieved")
        self._temporary_password = None
        return password

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "user": self.user,
            "temporary_password_available": self._temporary_password is not None,
        }

    def __repr__(self) -> str:
        return f"TemporaryCredential(user={self.user!r}, temporary_password=<redacted>)"

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        memo[id(self)] = self
        return self

    def __reduce__(self) -> NoReturn:
        raise TypeError("TemporaryCredential cannot be pickled")
