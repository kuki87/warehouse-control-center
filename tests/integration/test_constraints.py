"""Database constraints protect data even if a caller bypasses future services."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm.exc import StaleDataError

from tests.fixtures.database import make_courier, make_shipment, make_user
from warehouse_control_center.domain.entities import AuditEvent
from warehouse_control_center.domain.exceptions import DuplicateUserError
from warehouse_control_center.infrastructure.database.engine import SessionFactory
from warehouse_control_center.infrastructure.database.models import (
    AuditEventModel,
    ShipmentModel,
    UserModel,
)
from warehouse_control_center.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


def _create_user(session_factory: SessionFactory, username: str = "operator") -> int:
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        persisted = unit_of_work.users.add(make_user(username))
        unit_of_work.commit()
    assert persisted.id is not None
    return persisted.id


def _counts(session_factory: SessionFactory) -> tuple[int, int]:
    with session_factory() as session:
        shipment_count = session.scalar(select(func.count()).select_from(ShipmentModel)) or 0
        audit_count = session.scalar(select(func.count()).select_from(AuditEventModel)) or 0
        return shipment_count, audit_count


def test_foreign_key_enforcement_rejects_missing_creator(
    session_factory: SessionFactory,
) -> None:
    with pytest.raises(IntegrityError):
        with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
            unit_of_work.shipments.add(make_shipment(999_999))
            unit_of_work.commit()


def test_equivalent_normalized_usernames_collide(session_factory: SessionFactory) -> None:
    _create_user(session_factory, "  ADMIN ")

    with pytest.raises(DuplicateUserError):
        with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
            unit_of_work.users.add(make_user("admin"))
            unit_of_work.commit()


def test_equivalent_normalized_courier_codes_collide(session_factory: SessionFactory) -> None:
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.couriers.add(make_courier(" Č-1878 "))
        unit_of_work.commit()

    with pytest.raises(IntegrityError):
        with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
            unit_of_work.couriers.add(make_courier("č-1878"))
            unit_of_work.commit()


@pytest.mark.parametrize("duplicate_field", ["tracking", "barcode"])
def test_equivalent_shipment_identifiers_collide(
    session_factory: SessionFactory, duplicate_field: str
) -> None:
    user_id = _create_user(session_factory)
    first = make_shipment(user_id, tracking_number=" ab 123 ", barcode=" bar 123 ")
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.shipments.add(first)
        unit_of_work.commit()

    second = make_shipment(
        user_id,
        tracking_number="AB123" if duplicate_field == "tracking" else "TRK-OTHER",
        barcode="BAR123" if duplicate_field == "barcode" else "BAR-OTHER",
    )
    with pytest.raises(IntegrityError):
        with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
            unit_of_work.shipments.add(second)
            unit_of_work.commit()


def test_invalid_role_is_rejected_by_database(session_factory: SessionFactory) -> None:
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES ('bad', 'bad', 'hash', 'INVALID')"
                )
            )


def test_invalid_status_is_rejected_by_database(session_factory: SessionFactory) -> None:
    user_id = _create_user(session_factory)
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.execute(
                text(
                    "INSERT INTO shipments "
                    "(tracking_number, tracking_number_normalized, barcode, barcode_normalized, "
                    "recipient_name, recipient_address, recipient_city, recipient_phone, "
                    "sender_name, status, received_at, created_by, version) "
                    "VALUES ('T1', 'T1', 'B1', 'B1', 'Name', 'Address', 'City', 'Phone', "
                    "'Sender', 'INVALID', CURRENT_TIMESTAMP, :user_id, 1)"
                ),
                {"user_id": user_id},
            )


@pytest.mark.parametrize("invalid_version", [0, -1])
def test_version_must_be_positive(
    session_factory: SessionFactory,
    invalid_version: int,
) -> None:
    user_id = _create_user(session_factory)
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.execute(
                text(
                    "INSERT INTO shipments "
                    "(tracking_number, tracking_number_normalized, barcode, barcode_normalized, "
                    "recipient_name, recipient_address, recipient_city, recipient_phone, "
                    "sender_name, status, received_at, created_by, version) "
                    "VALUES ('T2', 'T2', 'B2', 'B2', 'Name', 'Address', 'City', 'Phone', "
                    "'Sender', 'RECEIVED', CURRENT_TIMESTAMP, :user_id, :invalid_version)"
                ),
                {"user_id": user_id, "invalid_version": invalid_version},
            )


def test_negative_failed_login_count_is_rejected(session_factory: SessionFactory) -> None:
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role, failed_login_attempts) "
                    "VALUES ('bad-count', 'bad-count', 'hash', 'ADMIN', -1)"
                )
            )


def test_negative_credential_version_is_rejected(session_factory: SessionFactory) -> None:
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role, credential_version) "
                    "VALUES ('bad-version', 'bad-version', "
                    "'$argon2id$v=19$m=1024,t=1,p=1$uym6DDygRmSpHGPrLLvt/w$"
                    "VdqOimLEoz+M7OQ4qVVsXZLSf8TC1UlslPiZi2f4K1I', 'ADMIN', -1)"
                )
            )


@pytest.mark.parametrize(
    ("username", "normalized", "password_hash", "must_change", "active"),
    [
        ("ab", "ab", "$argon2id$hash", 0, 1),
        (" padded ", "padded", "$argon2id$hash", 0, 1),
        ("valid-name", "   ", "$argon2id$hash", 0, 1),
        ("valid-name", "valid-name", "plaintext", 0, 1),
        ("valid-name", "valid-name", "$ARGON2ID$uppercase", 0, 1),
        ("valid-name", "valid-name", "$argon2id$garbage", 0, 1),
        ("valid-name", "valid-name", "$argon2id$" + "x" * 256, 0, 1),
        ("valid-name", "valid-name", "$argon2id$v=19$m=1,t=1,p=1$a$b", 2, 1),
        ("valid-name", "valid-name", "$argon2id$v=19$m=1,t=1,p=1$a$b", 0, 7),
    ],
)
def test_phase2_user_invariants_are_enforced_at_database_boundary(
    session_factory: SessionFactory,
    username: str,
    normalized: str,
    password_hash: str,
    must_change: int,
    active: int,
) -> None:
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role, "
                    "must_change_password, active) "
                    "VALUES (:username, :normalized, :password_hash, 'ADMIN', "
                    ":must_change, :active)"
                ),
                {
                    "username": username,
                    "normalized": normalized,
                    "password_hash": password_hash,
                    "must_change": must_change,
                    "active": active,
                },
            )


def test_nonexistent_courier_is_rejected(session_factory: SessionFactory) -> None:
    user_id = _create_user(session_factory)
    shipment = make_shipment(user_id)
    shipment.courier_id = 999_999

    with pytest.raises(IntegrityError):
        with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
            unit_of_work.shipments.add(shipment)


@pytest.mark.parametrize(
    ("missing_relation", "shipment_id", "changed_by"),
    [
        ("shipment", 999_999, None),
        ("user", None, 999_999),
    ],
)
def test_status_history_foreign_keys_are_enforced(
    session_factory: SessionFactory,
    missing_relation: str,
    shipment_id: int | None,
    changed_by: int | None,
) -> None:
    user_id = _create_user(session_factory)
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        shipment = unit_of_work.shipments.add(make_shipment(user_id))
        unit_of_work.commit()
    assert shipment.id is not None

    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        with session_factory.begin() as session:
            session.execute(
                text(
                    "INSERT INTO shipment_status_history "
                    "(shipment_id, old_status, new_status, changed_by) "
                    "VALUES (:shipment_id, 'RECEIVED', 'SORTING', :changed_by)"
                ),
                {
                    "shipment_id": shipment_id if missing_relation == "shipment" else shipment.id,
                    "changed_by": changed_by if missing_relation == "user" else user_id,
                },
            )


def test_required_columns_reject_null(session_factory: SessionFactory) -> None:
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES (NULL, 'missing', 'hash', 'ADMIN')"
                )
            )


def test_archive_fields_and_unicode_round_trip(session_factory: SessionFactory) -> None:
    archived_at = datetime.now(UTC)
    user = make_user("ČĆŽŠĐ")
    user.archived_at = archived_at
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        persisted_user = unit_of_work.users.add(user)
        persisted_courier = unit_of_work.couriers.add(make_courier("Đ-ČĆŽŠ"))
        unit_of_work.commit()

    assert persisted_user.id is not None
    assert persisted_courier.id is not None
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        loaded_user = unit_of_work.users.get_by_id(persisted_user.id)
        loaded_courier = unit_of_work.couriers.get_by_id(persisted_courier.id)

    assert loaded_user is not None
    assert loaded_user.username == "ČĆŽŠĐ"
    assert loaded_user.archived_at is not None
    assert loaded_user.archived_at.tzinfo is not None
    assert loaded_courier is not None
    assert loaded_courier.courier_code == "Đ-ČĆŽŠ"


def test_shipment_and_audit_are_atomic_when_audit_fails(
    session_factory: SessionFactory,
) -> None:
    user_id = _create_user(session_factory)

    with pytest.raises(IntegrityError):
        with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
            shipment = unit_of_work.shipments.add(make_shipment(user_id))
            assert shipment.id is not None
            unit_of_work.audits.add(
                AuditEvent(
                    actor_id=user_id,
                    actor_name_snapshot=None,
                    action="shipment.created",
                    entity_type="shipment",
                    entity_id=str(shipment.id),
                )
            )
            unit_of_work.commit()

    assert _counts(session_factory) == (0, 0)

    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        recovered_shipment = unit_of_work.shipments.add(
            make_shipment(user_id, tracking_number="RECOVERED", barcode="RECOVERED")
        )
        assert recovered_shipment.id is not None
        unit_of_work.audits.add(
            AuditEvent(
                actor_id=user_id,
                actor_name_snapshot="Operator",
                action="shipment.created",
                entity_type="shipment",
                entity_id=str(recovered_shipment.id),
            )
        )
        unit_of_work.commit()

    assert _counts(session_factory) == (1, 1)
    with session_factory() as session:
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []


def test_shipment_and_audit_rollback_after_python_exception(
    session_factory: SessionFactory,
) -> None:
    user_id = _create_user(session_factory)

    with pytest.raises(RuntimeError, match="after both flushes"):
        with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
            shipment = unit_of_work.shipments.add(make_shipment(user_id))
            unit_of_work.audits.add(
                AuditEvent(
                    actor_id=user_id,
                    actor_name_snapshot="Željko Šarić",
                    action="shipment.created",
                    entity_type="shipment",
                    entity_id=str(shipment.id),
                )
            )
            raise RuntimeError("after both flushes")

    assert _counts(session_factory) == (0, 0)
    with session_factory() as session:
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []


def test_stale_concurrent_shipment_update_is_detected(
    session_factory: SessionFactory,
) -> None:
    user_id = _create_user(session_factory)
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        shipment = unit_of_work.shipments.add(make_shipment(user_id))
        unit_of_work.commit()
    assert shipment.id is not None

    first_session = session_factory()
    second_session = session_factory()
    try:
        first_copy = first_session.get(ShipmentModel, shipment.id)
        stale_copy = second_session.get(ShipmentModel, shipment.id)
        assert first_copy is not None
        assert stale_copy is not None

        first_copy.notes = "first writer"
        first_session.commit()
        assert first_copy.version == 2

        stale_copy.notes = "stale writer"
        with pytest.raises(StaleDataError):
            second_session.commit()
        second_session.rollback()
        persisted = second_session.get(ShipmentModel, shipment.id)
        assert persisted is not None
        assert persisted.notes == "first writer"
        assert persisted.version == 2
        assert second_session.scalar(select(func.count()).select_from(ShipmentModel)) == 1
    finally:
        first_session.close()
        second_session.close()


def test_audit_repository_is_append_only(session_factory: SessionFactory) -> None:
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        assert not hasattr(unit_of_work.audits, "update")
        assert not hasattr(unit_of_work.audits, "delete")


def test_repository_lookups_apply_normalization(session_factory: SessionFactory) -> None:
    user_id = _create_user(session_factory, "Željko")
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        shipment = unit_of_work.shipments.add(
            make_shipment(user_id, tracking_number="TR K-900", barcode="BC 900")
        )
        unit_of_work.commit()
    assert shipment.id is not None

    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        assert unit_of_work.users.get_by_normalized_username("  ŽELJKO ") is not None
        assert unit_of_work.shipments.get_by_normalized_tracking_number("trk-900") is not None
        assert unit_of_work.shipments.get_by_normalized_barcode("bc900") is not None


def test_archived_identifiers_remain_reserved(session_factory: SessionFactory) -> None:
    archived_at = datetime.now(UTC)
    user_id = _create_user(session_factory, "reserved-user")
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        user_model = unit_of_work.session.get(UserModel, user_id)
        assert user_model is not None
        user_model.archived_at = archived_at
        courier = make_courier("reserved-courier")
        courier.archived_at = archived_at
        persisted_courier = unit_of_work.couriers.add(courier)
        shipment = make_shipment(
            user_id,
            tracking_number="reserved-tracking",
            barcode="reserved-barcode",
        )
        shipment.archived_at = archived_at
        unit_of_work.shipments.add(shipment)
        unit_of_work.commit()
    assert persisted_courier.id is not None

    duplicate_factories = (
        lambda: ("user", make_user("RESERVED-USER")),
        lambda: ("courier", make_courier("RESERVED-COURIER")),
        lambda: (
            "shipment",
            make_shipment(
                user_id,
                tracking_number="RESERVED-TRACKING",
                barcode="different-barcode",
            ),
        ),
        lambda: (
            "shipment",
            make_shipment(
                user_id,
                tracking_number="different-tracking",
                barcode="RESERVED-BARCODE",
            ),
        ),
    )
    for factory in duplicate_factories:
        repository_name, entity = factory()
        with pytest.raises((IntegrityError, DuplicateUserError)):
            with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
                getattr(unit_of_work, f"{repository_name}s").add(entity)


def test_audit_json_rejects_orm_objects_instead_of_serializing_them(
    session_factory: SessionFactory,
) -> None:
    user_id = _create_user(session_factory)

    with pytest.raises(StatementError):
        with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
            unit_of_work.audits.add(
                AuditEvent(
                    actor_id=user_id,
                    actor_name_snapshot="Operator",
                    action="unsafe.details",
                    entity_type="user",
                    entity_id=str(user_id),
                    details={"model": UserModel()},
                )
            )

    assert _counts(session_factory)[1] == 0
