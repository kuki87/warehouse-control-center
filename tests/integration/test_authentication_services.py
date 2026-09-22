"""Hostile integration tests for first-run, login, lockout, and user administration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import func, select, text

from tests.fixtures.database import upgrade_to_head
from warehouse_control_center.application.dto import SessionContext
from warehouse_control_center.application.permissions import require_permission
from warehouse_control_center.application.services import (
    AuthenticationService,
    FirstRunAdministratorService,
    UserService,
)
from warehouse_control_center.config.settings import Settings
from warehouse_control_center.domain.enums import AuditAction, Permission, UserRole
from warehouse_control_center.domain.exceptions import (
    AuthenticationError,
    DatabaseBusyError,
    DuplicateUserError,
    InvalidCurrentPasswordError,
    InvalidPasswordError,
    InvalidUserStateError,
    LastActiveAdministratorError,
    PasswordChangeRequiredError,
    PermissionDeniedError,
    UserNotFoundError,
)
from warehouse_control_center.infrastructure.database.engine import (
    SessionFactory,
    create_session_factory,
    create_sqlite_engine,
)
from warehouse_control_center.infrastructure.database.models import AuditEventModel, UserModel
from warehouse_control_center.infrastructure.database.repositories.audit import (
    SqlAlchemyAuditRepository,
)
from warehouse_control_center.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from warehouse_control_center.infrastructure.security import (
    Argon2PasswordHasher,
    SecureTemporaryPasswordGenerator,
)


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, **kwargs: float) -> None:
        self.current += timedelta(**kwargs)


class CountingDummyHasher:
    def __init__(self) -> None:
        self.hash_calls = 0
        self.verify_calls = 0

    def hash_password(self, password: str) -> str:
        del password
        self.hash_calls += 1
        return "$argon2id$dummy-hash"

    def verify_password(self, password_hash: str, password: str) -> bool:
        del password_hash, password
        self.verify_calls += 1
        return False

    def needs_rehash(self, password_hash: str) -> bool:
        del password_hash
        return False


def _services(
    session_factory: SessionFactory,
) -> tuple[FirstRunAdministratorService, AuthenticationService, UserService, FakeClock]:
    clock = FakeClock()
    hasher = Argon2PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    generator = SecureTemporaryPasswordGenerator()

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    return (
        FirstRunAdministratorService(uow_factory, hasher, generator, clock),
        AuthenticationService(uow_factory, hasher, clock),
        UserService(uow_factory, hasher, generator, clock),
        clock,
    )


def _initialize(
    session_factory: SessionFactory,
) -> tuple[AuthenticationService, UserService, FakeClock, SessionContext, str]:
    first_run, authentication, users, clock = _services(session_factory)
    credential = first_run.initialize()
    assert credential is not None
    password = credential.take_temporary_password()
    session = authentication.login("ADMIN", password)
    return authentication, users, clock, session, password


def test_first_admin_is_secure_idempotent_and_audited(
    session_factory: SessionFactory,
) -> None:
    first_run, authentication, _, _ = _services(session_factory)

    credential = first_run.initialize()
    assert credential is not None
    password = credential.take_temporary_password()
    assert credential.user.role is UserRole.ADMIN
    assert credential.user.must_change_password
    assert first_run.initialize() is None

    restricted = authentication.login("  AdMiN ", password)
    assert restricted.must_change_password
    with pytest.raises(PasswordChangeRequiredError):
        require_permission(restricted, Permission.MANAGE_USERS)

    with session_factory() as database:
        stored = database.scalar(select(UserModel))
        events = list(database.scalars(select(AuditEventModel)))
    assert stored is not None
    assert password != stored.password_hash
    assert password not in repr(stored)
    assert [event.action for event in events].count(AuditAction.FIRST_ADMIN_CREATED.value) == 1
    assert password not in repr([event.details_json for event in events])


def test_existing_user_prevents_first_admin_regeneration(
    session_factory: SessionFactory,
) -> None:
    first_run, _, _, _ = _services(session_factory)
    credential = first_run.initialize()
    assert credential is not None
    credential.take_temporary_password()
    assert first_run.initialize() is None


@pytest.mark.parametrize(
    ("role", "active", "archived"),
    [
        (UserRole.WAREHOUSE_OPERATOR, True, False),
        (UserRole.SUPERVISOR, False, False),
        (UserRole.ADMIN, False, True),
    ],
)
def test_any_existing_user_state_prevents_bootstrap_administrator_creation(
    session_factory: SessionFactory,
    role: UserRole,
    active: bool,
    archived: bool,
) -> None:
    first_run, _, _, clock = _services(session_factory)
    with session_factory.begin() as database:
        database.add(
            UserModel(
                username="existing-user",
                username_normalized="existing-user",
                password_hash=(
                    "$argon2id$v=19$m=1024,t=1,p=1$uym6DDygRmSpHGPrLLvt/w$"
                    "VdqOimLEoz+M7OQ4qVVsXZLSf8TC1UlslPiZi2f4K1I"
                ),
                role=role,
                active=active,
                archived_at=clock.now() if archived else None,
            )
        )

    assert first_run.initialize() is None
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(UserModel)) == 1


def test_login_failures_are_generic_and_do_not_create_users(
    session_factory: SessionFactory,
) -> None:
    authentication, _, _, _, password = _initialize(session_factory)
    attempted_password = "attacker-password-value"

    for username, supplied in (
        ("unknown", attempted_password),
        ("admin", attempted_password),
        ("\n", attempted_password),
        ("admin", "x" * 1025),
    ):
        with pytest.raises(AuthenticationError) as error:
            authentication.login(username, supplied)
        assert str(error.value) == "Invalid username or password."
        assert supplied not in str(error.value)

    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(UserModel)) == 1
        details = repr(list(database.scalars(select(AuditEventModel.details_json))))
    assert attempted_password not in details
    assert password not in details


def test_unknown_users_reuse_one_dummy_hash_but_still_verify_each_attempt(
    session_factory: SessionFactory,
) -> None:
    clock = FakeClock()
    hasher = CountingDummyHasher()

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    authentication = AuthenticationService(uow_factory, hasher, clock)
    assert hasher.hash_calls == 1
    for _ in range(2):
        with pytest.raises(AuthenticationError):
            authentication.login("unknown", "supplied-password")
    assert hasher.hash_calls == 1
    assert hasher.verify_calls == 2


def test_password_change_unlocks_full_session_and_old_password_stops_working(
    session_factory: SessionFactory,
) -> None:
    authentication, users, _, restricted, old_password = _initialize(session_factory)
    new_password = "nova veoma duga šifra"

    full = users.change_password(restricted, old_password, new_password)
    assert not full.must_change_password
    require_permission(full, Permission.MANAGE_USERS)
    with pytest.raises(AuthenticationError):
        authentication.login("admin", old_password)
    logged_in = authentication.login("admin", new_password)
    assert not logged_in.must_change_password
    authentication.logout(logged_in)
    with session_factory() as database:
        actions = list(database.scalars(select(AuditEventModel.action)))
    assert AuditAction.PASSWORD_CHANGED.value in actions
    assert AuditAction.LOGOUT.value in actions


def test_successful_login_rehashes_outdated_argon_parameters(
    session_factory: SessionFactory,
) -> None:
    clock = FakeClock()
    weak = Argon2PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    strong = Argon2PasswordHasher(time_cost=2, memory_cost=1024, parallelism=1)
    generator = SecureTemporaryPasswordGenerator()

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    credential = FirstRunAdministratorService(uow_factory, weak, generator, clock).initialize()
    assert credential is not None
    password = credential.take_temporary_password()
    with session_factory() as database:
        before = database.scalar(select(UserModel.password_hash))
    assert before is not None and strong.needs_rehash(before)

    AuthenticationService(uow_factory, strong, clock).login("admin", password)

    with session_factory() as database:
        after = database.scalar(select(UserModel.password_hash))
    assert after is not None
    assert after != before
    assert strong.verify_password(after, password)
    assert not strong.needs_rehash(after)


def test_lockout_persists_across_service_restart_and_grows_to_cap(
    session_factory: SessionFactory,
) -> None:
    authentication, _, clock, _, password = _initialize(session_factory)

    for _ in range(5):
        with pytest.raises(AuthenticationError):
            authentication.login("admin", "wrong-password")
    with session_factory() as database:
        user = database.scalar(select(UserModel))
        assert user is not None
        assert user.failed_login_attempts == 5
        assert user.locked_until == clock.now() + timedelta(seconds=30)

    _, restarted, _, _ = _services(session_factory)
    with pytest.raises(AuthenticationError):
        restarted.login("admin", password)

    expected_seconds = [60, 120, 240, 480, 900, 900]
    for seconds in expected_seconds:
        clock.advance(seconds=901)
        with pytest.raises(AuthenticationError):
            authentication.login("admin", "still-wrong")
        with session_factory() as database:
            user = database.scalar(select(UserModel))
            assert user is not None and user.locked_until is not None
            assert user.locked_until - clock.now() == timedelta(seconds=seconds)

    clock.advance(seconds=901)
    assert authentication.login("admin", password).user_id == 1
    with session_factory() as database:
        user = database.scalar(select(UserModel))
        assert user is not None
        assert user.failed_login_attempts == 0
        assert user.locked_until is None


def test_inactive_and_archived_accounts_have_same_external_failure(
    session_factory: SessionFactory,
) -> None:
    authentication, users, _, restricted, password = _initialize(session_factory)
    admin = users.change_password(restricted, password, "full-admin-password")
    created = users.create_user(admin, "worker", UserRole.WAREHOUSE_OPERATOR)
    worker_password = created.take_temporary_password()
    users.deactivate_user(admin, created.user.id)

    with pytest.raises(AuthenticationError, match="Invalid username or password"):
        authentication.login("worker", worker_password)
    users.activate_user(admin, created.user.id)
    users.archive_user(admin, created.user.id)
    with pytest.raises(AuthenticationError, match="Invalid username or password"):
        authentication.login("worker", worker_password)


def test_user_administration_permissions_duplicates_states_and_last_admin(
    session_factory: SessionFactory,
) -> None:
    authentication, users, _, restricted, password = _initialize(session_factory)
    admin = users.change_password(restricted, password, "full-admin-password")

    operator = SessionContext(999, "operator", UserRole.WAREHOUSE_OPERATOR, admin.authenticated_at)
    supervisor = SessionContext(998, "supervisor", UserRole.SUPERVISOR, admin.authenticated_at)
    for unauthorized in (operator, supervisor):
        with pytest.raises(PermissionDeniedError):
            users.create_user(unauthorized, "denied", UserRole.WAREHOUSE_OPERATOR)

    created = users.create_user(admin, "Željko", UserRole.WAREHOUSE_OPERATOR)
    temporary_password = created.take_temporary_password()
    with pytest.raises(DuplicateUserError):
        users.create_user(admin, "Z\u030cELJKO", UserRole.SUPERVISOR)

    changed = users.change_role(admin, created.user.id, UserRole.SUPERVISOR)
    assert changed.role is UserRole.SUPERVISOR
    renamed = users.change_username(admin, created.user.id, "Željko.Novi")
    assert renamed.username == "Željko.Novi"
    users.deactivate_user(admin, created.user.id)
    users.activate_user(admin, created.user.id)
    users.archive_user(admin, created.user.id)
    assert users.list_users(admin) == [users.get_user(admin, admin.user_id)]
    restored = users.restore_user(admin, created.user.id)
    assert not restored.active and restored.archived_at is None
    users.activate_user(admin, created.user.id)

    reset = users.reset_password(admin, created.user.id)
    reset_password = reset.take_temporary_password()
    assert reset_password != temporary_password
    forced = authentication.login("željko.novi", reset_password)
    assert forced.must_change_password

    with pytest.raises(LastActiveAdministratorError):
        users.deactivate_user(admin, admin.user_id)
    with pytest.raises(LastActiveAdministratorError):
        users.archive_user(admin, admin.user_id)
    with pytest.raises(LastActiveAdministratorError):
        users.change_role(admin, admin.user_id, UserRole.SUPERVISOR)


def test_user_and_audit_mutation_roll_back_together(
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, users, _, restricted, password = _initialize(session_factory)
    admin = users.change_password(restricted, password, "full-admin-password")

    def fail_audit(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        users.create_user(admin, "rollback-user", UserRole.WAREHOUSE_OPERATOR)

    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(UserModel)) == 1


def test_failed_login_counter_rolls_back_when_audit_fails(
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authentication, _, _, _, _ = _initialize(session_factory)

    def fail_audit(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        authentication.login("admin", "wrong-password")

    with session_factory() as database:
        user = database.scalar(select(UserModel))
        assert user is not None
        assert user.failed_login_attempts == 0


def test_first_admin_creation_rolls_back_when_audit_fails(
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_run, _, _, _ = _services(session_factory)

    def fail_audit(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        first_run.initialize()

    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(UserModel)) == 0


def test_successful_login_rehash_and_reset_roll_back_when_audit_fails(
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    weak = Argon2PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    strong = Argon2PasswordHasher(time_cost=2, memory_cost=1024, parallelism=1)
    generator = SecureTemporaryPasswordGenerator()

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    credential = FirstRunAdministratorService(uow_factory, weak, generator, clock).initialize()
    assert credential is not None
    password = credential.take_temporary_password()
    with session_factory.begin() as database:
        user = database.scalar(select(UserModel))
        assert user is not None
        original_hash = user.password_hash
        user.failed_login_attempts = 3

    def fail_audit(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", fail_audit)
    authentication = AuthenticationService(uow_factory, strong, clock)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        authentication.login("admin", password)

    with session_factory() as database:
        user = database.scalar(select(UserModel))
        assert user is not None
        assert user.password_hash == original_hash
        assert user.failed_login_attempts == 3
        assert strong.verify_password(user.password_hash, password)


def test_password_change_and_admin_reset_roll_back_when_audit_fails(
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, users, _, restricted, password = _initialize(session_factory)
    admin = users.change_password(restricted, password, "full-admin-password")
    operator = users.create_user(admin, "operator", UserRole.WAREHOUSE_OPERATOR).user
    with session_factory() as database:
        admin_before = database.get(UserModel, admin.user_id)
        operator_before = database.get(UserModel, operator.id)
        assert admin_before is not None and operator_before is not None
        admin_hash = admin_before.password_hash
        operator_hash = operator_before.password_hash

    def fail_audit(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        users.change_password(admin, "full-admin-password", "replacement-password")
    with pytest.raises(RuntimeError, match="audit unavailable"):
        users.reset_password(admin, operator.id)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        users.change_role(admin, operator.id, UserRole.SUPERVISOR)

    with session_factory() as database:
        admin_after = database.get(UserModel, admin.user_id)
        operator_after = database.get(UserModel, operator.id)
        assert admin_after is not None and operator_after is not None
        assert admin_after.password_hash == admin_hash
        assert operator_after.password_hash == operator_hash
        assert operator_after.role is UserRole.WAREHOUSE_OPERATOR


def test_forged_and_stale_admin_sessions_are_rejected_by_current_database_state(
    session_factory: SessionFactory,
) -> None:
    authentication, users, _, restricted, password = _initialize(session_factory)
    admin = users.change_password(restricted, password, "full-admin-password")
    operator = users.create_user(admin, "operator", UserRole.WAREHOUSE_OPERATOR).user

    forged = SessionContext(
        operator.id,
        operator.username,
        UserRole.ADMIN,
        admin.authenticated_at,
    )
    nonexistent = SessionContext(999_999, "ghost", UserRole.ADMIN, admin.authenticated_at)
    for invalid_session in (forged, nonexistent):
        with pytest.raises(PermissionDeniedError, match="no longer authorized"):
            users.create_user(invalid_session, "must-not-exist", UserRole.WAREHOUSE_OPERATOR)
    authentication.logout(nonexistent)

    second_credential = users.create_user(admin, "second-admin", UserRole.ADMIN)
    second_password = second_credential.take_temporary_password()
    second_restricted = authentication.login("second-admin", second_password)
    second_admin = users.change_password(second_restricted, second_password, "second-full-password")

    users.deactivate_user(admin, second_admin.user_id)
    with pytest.raises(PermissionDeniedError, match="no longer authorized"):
        users.list_users(second_admin)

    users.activate_user(admin, second_admin.user_id)
    users.change_role(admin, second_admin.user_id, UserRole.SUPERVISOR)
    with pytest.raises(PermissionDeniedError, match="no longer authorized"):
        users.create_user(second_admin, "stale-role", UserRole.WAREHOUSE_OPERATOR)

    users.change_role(admin, second_admin.user_id, UserRole.ADMIN)
    users.archive_user(admin, second_admin.user_id)
    with pytest.raises(PermissionDeniedError, match="no longer authorized"):
        users.get_user(second_admin, admin.user_id)

    with session_factory() as database:
        names = set(database.scalars(select(UserModel.username)))
    assert "must-not-exist" not in names
    assert "stale-role" not in names
    with session_factory() as database:
        logout = database.scalar(
            select(AuditEventModel)
            .where(AuditEventModel.action == AuditAction.LOGOUT.value)
            .order_by(AuditEventModel.id.desc())
        )
    assert logout is not None and logout.actor_id is None


def test_password_rotation_invalidates_older_administrator_sessions(
    session_factory: SessionFactory,
) -> None:
    authentication, users, _, restricted, password = _initialize(session_factory)
    first_admin = users.change_password(restricted, password, "first-admin-password")
    second_credential = users.create_user(first_admin, "second-admin", UserRole.ADMIN)
    second_password = second_credential.take_temporary_password()
    second_restricted = authentication.login("second-admin", second_password)
    second_admin = users.change_password(second_restricted, second_password, "second-password")

    users.reset_password(first_admin, second_admin.user_id)
    with pytest.raises(PermissionDeniedError, match="no longer authorized"):
        users.create_user(second_admin, "stale-after-reset", UserRole.WAREHOUSE_OPERATOR)

    refreshed_first = users.change_password(
        first_admin, "first-admin-password", "first-admin-password-new"
    )
    with pytest.raises(PermissionDeniedError, match="no longer authorized"):
        users.list_users(first_admin)
    assert users.list_users(refreshed_first)


def test_mandatory_password_change_cannot_be_cleared_by_reusing_temporary_password(
    session_factory: SessionFactory,
) -> None:
    authentication, _, _, restricted, password = _initialize(session_factory)

    with pytest.raises(InvalidPasswordError, match="must differ"):
        authentication.change_password(restricted, password, password)

    assert authentication.login("admin", password).must_change_password


def test_password_change_rejects_invalid_inputs_and_preserves_supplied_characters(
    session_factory: SessionFactory,
) -> None:
    authentication, users, _, restricted, password = _initialize(session_factory)

    with pytest.raises(InvalidCurrentPasswordError):
        users.change_password(restricted, "wrong-current-password", "valid-new-password")
    for invalid in ("short", " " * 12, "x" * 1025):
        with pytest.raises(InvalidPasswordError):
            users.change_password(restricted, password, invalid)

    supplied = "  Unicode-Å¡ifra\nwith-control  "
    full = users.change_password(restricted, password, supplied)
    assert not full.must_change_password
    assert authentication.login("admin", supplied).user_id == full.user_id


def test_password_change_rejects_missing_inactive_and_corrupted_accounts(
    session_factory: SessionFactory,
) -> None:
    _, users, _, restricted, password = _initialize(session_factory)
    missing = replace(restricted, user_id=999_999)
    with pytest.raises(UserNotFoundError):
        users.change_password(missing, password, "valid-new-password")

    admin = users.change_password(restricted, password, "full-admin-password")
    second_credential = users.create_user(admin, "inactive-user", UserRole.WAREHOUSE_OPERATOR)
    second_password = second_credential.take_temporary_password()
    inactive_session = replace(
        restricted,
        user_id=second_credential.user.id,
        username=second_credential.user.username,
        role=UserRole.WAREHOUSE_OPERATOR,
    )
    users.deactivate_user(admin, inactive_session.user_id)
    with pytest.raises(InvalidUserStateError, match="not active"):
        users.change_password(inactive_session, second_password, "valid-new-password")

    with session_factory.begin() as database:
        database.execute(text("PRAGMA ignore_check_constraints=ON"))
        database.execute(
            text("UPDATE users SET password_hash = '$argon2id$broken' WHERE id = :user_id"),
            {"user_id": admin.user_id},
        )
        database.execute(text("PRAGMA ignore_check_constraints=OFF"))
    with pytest.raises(InvalidUserStateError, match="administrator reset"):
        users.change_password(admin, "full-admin-password", "another-valid-password")


def test_admin_password_reset_state_and_target_rules(
    session_factory: SessionFactory,
) -> None:
    authentication, users, _, restricted, password = _initialize(session_factory)
    admin = users.change_password(restricted, password, "full-admin-password")
    operator_credential = users.create_user(admin, "operator", UserRole.WAREHOUSE_OPERATOR)
    operator_password = operator_credential.take_temporary_password()
    operator_session = authentication.login("operator", operator_password)
    users.deactivate_user(admin, operator_session.user_id)

    reset = users.reset_password(admin, operator_session.user_id)
    reset_password = reset.take_temporary_password()
    assert reset.user.must_change_password
    with pytest.raises(AuthenticationError):
        authentication.login("operator", reset_password)

    second_admin_credential = users.create_user(admin, "second-admin", UserRole.ADMIN)
    second_admin_password = second_admin_credential.take_temporary_password()
    reset_admin = users.reset_password(admin, second_admin_credential.user.id)
    assert reset_admin.user.must_change_password
    assert reset_admin.take_temporary_password() != second_admin_password

    with pytest.raises(PermissionDeniedError):
        users.reset_password(operator_session, second_admin_credential.user.id)
    with pytest.raises(InvalidUserStateError, match="own password"):
        users.reset_password(admin, admin.user_id)
    with pytest.raises(UserNotFoundError):
        users.reset_password(admin, 999_999)
    users.archive_user(admin, operator_session.user_id)
    with pytest.raises(InvalidUserStateError, match="archived"):
        users.reset_password(admin, operator_session.user_id)


def test_corrupted_stored_hash_fails_with_generic_authentication_error(
    session_factory: SessionFactory,
) -> None:
    authentication, _, _, _, _ = _initialize(session_factory)
    with session_factory.begin() as database:
        database.execute(text("PRAGMA ignore_check_constraints=ON"))
        database.execute(
            text(
                "UPDATE users SET password_hash = "
                "'$argon2i$v=19$m=1024,t=1,p=1$c2FsdHNhbHQ$ZmFrZWhhc2hmYWtl' "
                "WHERE username_normalized = 'admin'"
            )
        )
        database.execute(text("PRAGMA ignore_check_constraints=OFF"))

    with pytest.raises(AuthenticationError) as error:
        authentication.login("admin", "any-password")
    assert str(error.value) == "Invalid username or password."

    with session_factory() as database:
        event = database.scalar(
            select(AuditEventModel)
            .where(AuditEventModel.action == AuditAction.LOGIN_FAILURE.value)
            .order_by(AuditEventModel.id.desc())
        )
    assert event is not None
    assert event.details_json == {"reason": "stored_credential_invalid"}


def test_lockout_expiry_boundaries_and_huge_counter_fail_safely(
    session_factory: SessionFactory,
) -> None:
    authentication, _, clock, _, password = _initialize(session_factory)
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            authentication.login("admin", "wrong-password")

    clock.advance(seconds=30, microseconds=-1)
    with pytest.raises(AuthenticationError):
        authentication.login("admin", password)

    clock.advance(microseconds=1)
    assert authentication.login("admin", password).user_id == 1

    with session_factory.begin() as database:
        user = database.scalar(select(UserModel))
        assert user is not None
        user.failed_login_attempts = 2**63 - 2
        user.locked_until = None
    with pytest.raises(AuthenticationError):
        authentication.login("admin", "wrong-password")
    with session_factory() as database:
        user = database.scalar(select(UserModel))
        assert user is not None and user.locked_until is not None
        assert user.failed_login_attempts == 2**63 - 1
        assert user.locked_until - clock.now() == timedelta(seconds=900)


def test_concurrent_first_run_creates_exactly_one_administrator(
    session_factory: SessionFactory,
) -> None:
    first_run, _, _, _ = _services(session_factory)
    barrier = Barrier(2)

    def initialize() -> object:
        barrier.wait()
        return first_run.initialize()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: initialize(), range(2)))

    assert sum(result is not None for result in results) == 1
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(UserModel)) == 1


def test_concurrent_failed_logins_do_not_lose_updates(
    session_factory: SessionFactory,
) -> None:
    authentication, users, _, restricted, password = _initialize(session_factory)
    users.change_password(restricted, password, "full-admin-password")
    barrier = Barrier(2)

    def fail_login() -> None:
        barrier.wait()
        with pytest.raises(AuthenticationError):
            authentication.login("admin", "wrong-password")

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: fail_login(), range(2)))

    with session_factory() as database:
        user = database.scalar(select(UserModel))
        assert user is not None
        assert user.failed_login_attempts == 2
        assert user.locked_until is None


def test_concurrent_success_and_failure_have_serializable_final_state(
    session_factory: SessionFactory,
) -> None:
    authentication, users, _, restricted, password = _initialize(session_factory)
    users.change_password(restricted, password, "full-admin-password")
    barrier = Barrier(2)

    def login(candidate: str) -> bool:
        barrier.wait()
        try:
            authentication.login("admin", candidate)
        except AuthenticationError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(login, ["full-admin-password", "wrong-password"]))

    assert sorted(results) == [False, True]
    with session_factory() as database:
        user = database.scalar(select(UserModel))
        assert user is not None
        assert user.failed_login_attempts in {0, 1}
        assert user.locked_until is None


@pytest.mark.parametrize("operation", ["deactivate_user", "archive_user", "demote"])
def test_cross_admin_races_cannot_remove_every_active_administrator(
    session_factory: SessionFactory,
    operation: str,
) -> None:
    authentication, users, _, restricted, password = _initialize(session_factory)
    first_admin = users.change_password(restricted, password, "first-full-password")
    second_credential = users.create_user(first_admin, "second-admin", UserRole.ADMIN)
    second_password = second_credential.take_temporary_password()
    second_restricted = authentication.login("second-admin", second_password)
    second_admin = users.change_password(second_restricted, second_password, "second-full-password")
    barrier = Barrier(2)

    def remove_other(actor: SessionContext, target_id: int) -> str:
        barrier.wait()
        try:
            if operation == "demote":
                users.change_role(actor, target_id, UserRole.SUPERVISOR)
            else:
                getattr(users, operation)(actor, target_id)
        except (LastActiveAdministratorError, PermissionDeniedError) as error:
            return type(error).__name__
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda arguments: remove_other(*arguments),
                [
                    (first_admin, second_admin.user_id),
                    (second_admin, first_admin.user_id),
                ],
            )
        )

    assert results.count("success") == 1
    with session_factory() as database:
        remaining = database.scalar(
            select(func.count())
            .select_from(UserModel)
            .where(
                UserModel.role == UserRole.ADMIN,
                UserModel.active.is_(True),
                UserModel.archived_at.is_(None),
            )
        )
    assert remaining == 1


def test_database_write_lock_is_translated_and_leaves_no_partial_state(
    test_settings: Settings,
) -> None:
    short_settings = replace(test_settings, sqlite_timeout_seconds=0.05)
    upgrade_to_head(short_settings)
    engine = create_sqlite_engine(short_settings)
    session_factory = create_session_factory(engine)
    first_run, authentication, _, _ = _services(session_factory)
    credential = first_run.initialize()
    assert credential is not None
    password = credential.take_temporary_password()
    blocker = engine.connect()
    try:
        blocker.exec_driver_sql("BEGIN IMMEDIATE")
        with pytest.raises(DatabaseBusyError, match="retry"):
            authentication.login("admin", password)
    finally:
        blocker.rollback()
        blocker.close()

    assert authentication.login("admin", password).must_change_password
    engine.dispose()
