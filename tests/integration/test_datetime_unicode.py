"""UTC timestamp and Bosnian Unicode behavior survives real SQLite round trips."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import StatementError

from tests.fixtures.database import make_courier, make_shipment, make_user
from warehouse_control_center.domain.normalization import normalize_username
from warehouse_control_center.infrastructure.database.engine import SessionFactory
from warehouse_control_center.infrastructure.database.models import UserModel
from warehouse_control_center.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


def test_bosnian_unicode_storage_retrieval_and_sqlite_query(
    session_factory: SessionFactory,
) -> None:
    user = make_user("Đorđe")
    courier = make_courier("ČĆŽŠĐ")
    courier.first_name = "Željko"
    courier.last_name = "Šarić Čavić Ćosić"

    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        persisted_user = unit_of_work.users.add(user)
        persisted_courier = unit_of_work.couriers.add(courier)
        assert persisted_user.id is not None
        shipment = make_shipment(persisted_user.id)
        persisted_shipment = unit_of_work.shipments.add(shipment)
        unit_of_work.commit()
    assert persisted_user.id is not None
    assert persisted_courier.id is not None
    assert persisted_shipment.id is not None

    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        loaded_user = unit_of_work.users.get_by_normalized_username("ĐORĐE")
        loaded_courier = unit_of_work.couriers.get_by_id(persisted_courier.id)
        loaded_shipment = unit_of_work.shipments.get_by_id(persisted_shipment.id)
        raw_username = unit_of_work.session.scalar(
            select(UserModel.username).where(
                UserModel.username_normalized == normalize_username("đorđe")
            )
        )

    assert loaded_user is not None and loaded_user.username == "Đorđe"
    assert loaded_courier is not None
    assert loaded_courier.first_name == "Željko"
    assert loaded_courier.last_name == "Šarić Čavić Ćosić"
    assert loaded_shipment is not None
    assert loaded_shipment.recipient_name == "Željko Šarić"
    assert loaded_shipment.sender_name == "Đorđe Čavić"
    assert raw_username == "Đorđe"


def test_aware_datetime_round_trip_is_normalized_to_utc(
    session_factory: SessionFactory,
) -> None:
    sarajevo = ZoneInfo("Europe/Sarajevo")
    local_time = datetime(2026, 7, 15, 12, 30, tzinfo=sarajevo)
    user = make_user("timestamp-user")
    user.locked_until = local_time

    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        persisted = unit_of_work.users.add(user)
        unit_of_work.commit()
    assert persisted.id is not None

    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        loaded = unit_of_work.users.get_by_id(persisted.id)

    assert loaded is not None
    assert loaded.locked_until == local_time.astimezone(UTC)
    assert loaded.locked_until is not None and loaded.locked_until.tzinfo is UTC


def test_naive_datetime_is_rejected(session_factory: SessionFactory) -> None:
    user = make_user("naive-time")
    user.locked_until = datetime(2026, 1, 1, 12, 0)

    with pytest.raises(StatementError, match="Naive datetime"):
        with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
            unit_of_work.users.add(user)


def test_server_generated_timestamp_is_restored_as_aware_utc(
    session_factory: SessionFactory,
) -> None:
    with session_factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO users (username, username_normalized, password_hash, role) "
                "VALUES ('server-time', 'server-time', "
                "'$argon2id$v=19$m=1024,t=1,p=1$uym6DDygRmSpHGPrLLvt/w$"
                "VdqOimLEoz+M7OQ4qVVsXZLSf8TC1UlslPiZi2f4K1I', 'ADMIN')"
            )
        )

    with session_factory() as session:
        loaded = session.scalar(
            select(UserModel).where(UserModel.username_normalized == "server-time")
        )

    assert loaded is not None
    assert loaded.created_at.tzinfo is UTC
    assert loaded.updated_at.tzinfo is UTC


def test_sarajevo_timezone_uses_zoneinfo_dst_rules() -> None:
    sarajevo = ZoneInfo("Europe/Sarajevo")
    winter = datetime(2026, 1, 15, 12, 0, tzinfo=sarajevo)
    summer = datetime(2026, 7, 15, 12, 0, tzinfo=sarajevo)

    assert sarajevo.key == "Europe/Sarajevo"
    assert winter.utcoffset() != summer.utcoffset()
