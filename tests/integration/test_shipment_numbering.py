"""Transactional, concurrent automatic shipment-number allocation."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import delete, select, update

from tests.fixtures.shipments import ShipmentHarness, build_shipment_harness
from warehouse_control_center.domain.enums import ShipmentStatus
from warehouse_control_center.domain.exceptions import (
    ShipmentNumberAllocationError,
    ShipmentNumberExhaustedError,
)
from warehouse_control_center.domain.shipment_numbering import (
    SHIPMENT_NUMBER_EXHAUSTED_VALUE,
    SHIPMENT_NUMBER_SEQUENCE_NAME,
)
from warehouse_control_center.infrastructure.database.engine import SessionFactory
from warehouse_control_center.infrastructure.database.models import (
    ShipmentModel,
    ShipmentNumberSequenceModel,
)
from warehouse_control_center.infrastructure.database.repositories.audit import (
    SqlAlchemyAuditRepository,
)
from warehouse_control_center.infrastructure.database.repositories.shipments import (
    SqlAlchemyShipmentRepository,
)


@pytest.fixture
def harness(session_factory: SessionFactory) -> ShipmentHarness:
    return build_shipment_harness(session_factory)


def _next_value(session_factory: SessionFactory) -> int | None:
    with session_factory() as database:
        return database.scalar(
            select(ShipmentNumberSequenceModel.next_value).where(
                ShipmentNumberSequenceModel.name == SHIPMENT_NUMBER_SEQUENCE_NAME
            )
        )


def test_concurrent_independent_sessions_allocate_unique_increasing_numbers(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    def create(index: int) -> str:
        return harness.service.create_shipment(
            harness.admin,
            recipient_name=f"Recipient {index}",
            recipient_address=f"Address {index}",
            recipient_city="Sarajevo",
            recipient_phone=f"+387 61 {index:06d}",
            sender_name="Concurrent Sender",
        ).shipment_number

    with ThreadPoolExecutor(max_workers=8) as executor:
        numbers = list(executor.map(create, range(20)))

    assert sorted(numbers) == [f"E{value:09d}" for value in range(1, 21)]
    assert len(numbers) == len(set(numbers))
    with session_factory() as database:
        persisted = list(
            database.scalars(select(ShipmentModel.shipment_number).order_by(ShipmentModel.id))
        )
    assert sorted(persisted) == sorted(numbers)
    assert _next_value(session_factory) == 21


def test_archived_or_deleted_shipments_never_make_numbers_reusable(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    first = harness.create()
    harness.service.archive_shipment(
        harness.admin,
        first.id,
        expected_version=first.version,
    )
    second = harness.create()
    with session_factory.begin() as database:
        database.execute(delete(ShipmentModel).where(ShipmentModel.id == second.id))
    third = harness.create()

    assert first.shipment_number == "E000000001"
    assert second.shipment_number == "E000000002"
    assert third.shipment_number == "E000000003"


def test_allocation_and_shipment_insert_roll_back_when_persistence_fails(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced shipment persistence failure")

    monkeypatch.setattr(SqlAlchemyShipmentRepository, "add", fail)
    with pytest.raises(RuntimeError, match="persistence failure"):
        harness.create()

    assert _next_value(session_factory) == 1
    with session_factory() as database:
        assert database.scalar(select(ShipmentModel.id)) is None


def test_allocation_rolls_back_with_audit_and_next_create_reuses_uncommitted_value(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_add = SqlAlchemyAuditRepository.add

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", fail)
    with pytest.raises(RuntimeError, match="forced audit failure"):
        harness.create()
    assert _next_value(session_factory) == 1

    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", original_add)
    created = harness.create()
    assert created.shipment_number == "E000000001"
    assert _next_value(session_factory) == 2


def test_exhausted_sequence_fails_explicitly_without_creating_shipment(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    with session_factory.begin() as database:
        database.execute(
            update(ShipmentNumberSequenceModel)
            .where(ShipmentNumberSequenceModel.name == SHIPMENT_NUMBER_SEQUENCE_NAME)
            .values(next_value=SHIPMENT_NUMBER_EXHAUSTED_VALUE)
        )

    with pytest.raises(ShipmentNumberExhaustedError):
        harness.create()
    with session_factory() as database:
        assert database.scalar(select(ShipmentModel.id)) is None


def test_missing_sequence_fails_explicitly_without_fallback(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    with session_factory.begin() as database:
        database.execute(
            delete(ShipmentNumberSequenceModel).where(
                ShipmentNumberSequenceModel.name == SHIPMENT_NUMBER_SEQUENCE_NAME
            )
        )

    with pytest.raises(ShipmentNumberAllocationError):
        harness.create()


def test_identifier_conflict_is_reported_as_allocation_failure_and_rolls_back(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    now = harness.clock.now()
    with session_factory.begin() as database:
        database.add(
            ShipmentModel(
                shipment_number="E000000001",
                shipment_number_normalized="E000000001",
                recipient_name="Legacy",
                recipient_address="Legacy address",
                recipient_city="Sarajevo",
                recipient_phone="123",
                sender_name="Legacy sender",
                status=ShipmentStatus.RECEIVED,
                received_at=now,
                created_at=now,
                updated_at=now,
                created_by=harness.admin.user_id,
                version=1,
            )
        )

    with pytest.raises(ShipmentNumberAllocationError):
        harness.create()
    assert _next_value(session_factory) == 1
