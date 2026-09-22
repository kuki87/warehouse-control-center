"""Phase 2 security primitives and complete authorization matrix."""

import copy
import json
import pickle
from dataclasses import FrozenInstanceError, asdict
from datetime import UTC, datetime
from typing import cast

import pytest
from argon2 import extract_parameters
from argon2.low_level import Type

from warehouse_control_center.application.dto import SessionContext, TemporaryCredential, UserDTO
from warehouse_control_center.application.permissions import (
    ROLE_PERMISSIONS,
    has_permission,
    require_permission,
)
from warehouse_control_center.application.services._time import utc_timestamp
from warehouse_control_center.application.services.lockout import lockout_duration
from warehouse_control_center.domain.enums import Permission, UserRole
from warehouse_control_center.domain.exceptions import (
    InvalidPasswordError,
    InvalidUsernameError,
    PermissionDeniedError,
    TemporaryCredentialConsumedError,
)
from warehouse_control_center.domain.validation import (
    PASSWORD_MAX_LENGTH,
    validate_password,
    validate_username,
)
from warehouse_control_center.infrastructure.security import (
    Argon2PasswordHasher,
    SecureTemporaryPasswordGenerator,
)


def _session(role: UserRole, *, must_change: bool = False) -> SessionContext:
    return SessionContext(1, "user", role, datetime(2026, 1, 1, tzinfo=UTC), must_change)


@pytest.mark.parametrize("role", list(UserRole))
@pytest.mark.parametrize("permission", list(Permission))
def test_full_role_permission_matrix(role: UserRole, permission: Permission) -> None:
    assert has_permission(_session(role), permission) is (permission in ROLE_PERMISSIONS[role])


@pytest.mark.parametrize("permission", list(Permission))
def test_mandatory_password_change_denies_every_permission(permission: Permission) -> None:
    assert not has_permission(_session(UserRole.ADMIN, must_change=True), permission)


def test_admin_has_every_declared_permission() -> None:
    assert ROLE_PERMISSIONS[UserRole.ADMIN] == frozenset(Permission)


def test_unknown_role_and_permission_fail_closed() -> None:
    unknown_role = cast(UserRole, "UNKNOWN")
    session = _session(unknown_role)
    unknown_permission = cast(Permission, object())

    assert not has_permission(session, Permission.MANAGE_USERS)
    assert not has_permission(_session(UserRole.ADMIN), unknown_permission)
    with pytest.raises(PermissionDeniedError):
        require_permission(session, Permission.MANAGE_USERS)
    with pytest.raises(PermissionDeniedError):
        require_permission(_session(UserRole.ADMIN), unknown_permission)


def test_session_is_immutable() -> None:
    session = _session(UserRole.ADMIN)
    with pytest.raises(FrozenInstanceError):
        session.username = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "value",
    [
        "",
        "  ",
        "ab",
        "a" * 65,
        "has space",
        "line\nbreak",
        "tab\tname",
        "zero\u200bwidth",
        "rtl\u200fmark",
        "name/part",
        "\ufdfa" * 4,
    ],
)
def test_invalid_usernames_are_rejected(value: str) -> None:
    with pytest.raises(InvalidUsernameError):
        validate_username(value)


def test_username_preserves_regional_unicode_and_normalizes_compatibility() -> None:
    assert validate_username("  Z\u030celjko_Ćosić-2  ") == "Željko_Ćosić-2"
    assert validate_username("Ａｄｍｉｎ") == "Admin"


@pytest.mark.parametrize("value", ["", " " * 12, "short", "x" * (PASSWORD_MAX_LENGTH + 1)])
def test_invalid_passwords_are_rejected(value: str) -> None:
    with pytest.raises(InvalidPasswordError):
        validate_password(value)


def test_password_policy_allows_unicode_and_spaces_without_mutation() -> None:
    validate_password("  veoma duga šifra 🔐  ")


def test_argon2id_hashing_verification_salts_and_rehash() -> None:
    fast = Argon2PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    stronger = Argon2PasswordHasher(time_cost=2, memory_cost=1024, parallelism=1)
    password = "duga Unicode šifra 🔐"

    first = fast.hash_password(password)
    second = fast.hash_password(password)

    assert first != second
    assert password not in first
    assert first.startswith("$argon2id$")
    assert fast.verify_password(first, password)
    assert not fast.verify_password(first, "pogrešna šifra")
    assert not fast.needs_rehash(first)
    assert stronger.needs_rehash(first)
    assert not fast.verify_password("not-a-hash", password)


def test_default_argon2_parameters_and_password_boundaries_are_real() -> None:
    hasher = Argon2PasswordHasher()
    minimum = "x" * 12
    maximum = "x" * PASSWORD_MAX_LENGTH

    minimum_hash = hasher.hash_password(minimum)
    maximum_hash = hasher.hash_password(maximum)
    parameters = extract_parameters(minimum_hash)

    assert parameters.type is Type.ID
    assert parameters.memory_cost == 65_536
    assert parameters.time_cost == 3
    assert parameters.parallelism == 4
    assert parameters.salt_len == 16
    assert parameters.hash_len == 32
    assert hasher.verify_password(minimum_hash, minimum)
    assert hasher.verify_password(maximum_hash, maximum)
    assert not hasher.verify_password(maximum_hash, "x" * 1023 + "y")
    with pytest.raises(InvalidPasswordError):
        validate_password("x" * (PASSWORD_MAX_LENGTH + 1))


def test_temporary_password_sample_has_no_duplicates_or_fixed_prefix() -> None:
    generator = SecureTemporaryPasswordGenerator()
    sample = [generator.generate() for _ in range(2_000)]

    assert len(set(sample)) == len(sample)
    assert len({password[:4] for password in sample}) > 1_900
    assert all(len(password) == 24 for password in sample)
    for password in sample:
        validate_password(password)


@pytest.mark.parametrize(
    "malformed",
    [
        "",
        "garbage",
        "$argon2id$",
        "$argon2i$v=19$m=1024,t=1,p=1$c2FsdHNhbHQ$ZmFrZWhhc2hmYWtl",
        "$argon2id$v=19$m=999999999,t=1,p=1$c2FsdHNhbHQ$ZmFrZWhhc2hmYWtl",
        "$argon2id$v=19$m=1024,t=999,p=1$c2FsdHNhbHQ$ZmFrZWhhc2hmYWtl",
        "$argon2id$v=19$m=1024,t=1,p=999$c2FsdHNhbHQ$ZmFrZWhhc2hmYWtl",
        "$argon2id$v=19$m=1024,t=1,p=1$invalid***$ZmFrZWhhc2hmYWtl",
        "$argon2id$" + "x" * 10_000,
    ],
)
def test_malformed_or_resource_abusive_hashes_fail_safely(malformed: str) -> None:
    hasher = Argon2PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)

    assert not hasher.verify_password(malformed, "candidate-password")
    assert hasher.needs_rehash(malformed)


def test_lockout_handles_maximum_database_integer_without_big_integer_explosion() -> None:
    duration = lockout_duration(2**63 - 1)
    assert duration is not None
    assert duration.total_seconds() == 900


def test_injected_clock_must_be_timezone_aware_and_is_normalized_to_utc() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        utc_timestamp(datetime(2026, 1, 1))

    assert utc_timestamp(datetime(2026, 1, 1, 1, tzinfo=UTC)) == datetime(2026, 1, 1, 1, tzinfo=UTC)


def test_temporary_credential_and_user_dto_do_not_serialize_secrets() -> None:
    dto = UserDTO(
        id=1,
        username="admin",
        role=UserRole.ADMIN,
        active=True,
        must_change_password=True,
        failed_login_attempts=0,
        locked_until=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        archived_at=None,
    )
    credential = TemporaryCredential(dto, "one-time-super-secret")

    rendered = repr(credential)
    serialized = repr(credential.to_safe_dict()) + repr(asdict(dto))
    assert "one-time-super-secret" not in rendered + serialized
    assert "password_hash" not in rendered + serialized
    assert str(credential) == rendered
    assert copy.copy(credential) is credential
    assert copy.deepcopy(credential) is credential
    with pytest.raises(TypeError, match="cannot be pickled"):
        pickle.dumps(credential)
    with pytest.raises(TypeError):
        json.dumps(credential)
    assert credential.take_temporary_password() == "one-time-super-secret"
    with pytest.raises(TemporaryCredentialConsumedError):
        credential.take_temporary_password()
