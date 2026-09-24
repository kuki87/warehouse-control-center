"""SQLite constraints defend shipment invariants below the application service."""

from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from tests.fixtures.shipments import build_shipment_harness
from warehouse_control_center.domain.enums import ProblemType, ShipmentStatus
from warehouse_control_center.infrastructure.database.engine import SessionFactory
from warehouse_control_center.infrastructure.database.models import (
    ShipmentProblemModel,
    ShipmentStatusHistoryModel,
)


def test_database_rejects_blank_identifiers_and_overlong_notes(
    session_factory: SessionFactory,
) -> None:
    harness = build_shipment_harness(session_factory)
    shipment = harness.create()
    with pytest.raises(IntegrityError):
        with session_factory.begin() as database:
            database.execute(
                shipment_table()
                .insert()
                .values(
                    tracking_number="",
                    tracking_number_normalized="",
                    recipient_name="Name",
                    recipient_address="Address",
                    recipient_city="City",
                    recipient_phone="123",
                    sender_name="Sender",
                    status=ShipmentStatus.RECEIVED.value,
                    received_at=harness.clock.now(),
                    created_by=shipment.created_by,
                    notes="x" * 4_001,
                    version=1,
                )
            )


def test_history_rejects_same_status_and_reasonless_override(
    session_factory: SessionFactory,
) -> None:
    harness = build_shipment_harness(session_factory)
    shipment = harness.create()
    for history in (
        ShipmentStatusHistoryModel(
            shipment_id=shipment.id,
            old_status=ShipmentStatus.RECEIVED,
            new_status=ShipmentStatus.RECEIVED,
            changed_by=harness.admin.user_id,
        ),
        ShipmentStatusHistoryModel(
            shipment_id=shipment.id,
            old_status=ShipmentStatus.RECEIVED,
            new_status=ShipmentStatus.DISPATCHED,
            changed_by=harness.admin.user_id,
            is_admin_override=True,
            reason=" ",
        ),
    ):
        with pytest.raises(IntegrityError):
            with session_factory.begin() as database:
                database.add(history)


def test_only_one_unresolved_problem_and_resolution_pairing_are_enforced(
    session_factory: SessionFactory,
) -> None:
    harness = build_shipment_harness(session_factory)
    shipment = harness.create()
    first = ShipmentProblemModel(
        shipment_id=shipment.id,
        problem_type=ProblemType.DAMAGED,
        previous_status=ShipmentStatus.RECEIVED,
        reported_by=harness.operator.user_id,
        reported_at=harness.clock.now(),
    )
    with session_factory.begin() as database:
        database.add(first)

    with pytest.raises(IntegrityError):
        with session_factory.begin() as database:
            database.add(
                ShipmentProblemModel(
                    shipment_id=shipment.id,
                    problem_type=ProblemType.NOT_FOUND,
                    previous_status=ShipmentStatus.RECEIVED,
                    reported_by=harness.operator.user_id,
                    reported_at=harness.clock.now(),
                )
            )

    with pytest.raises(IntegrityError):
        with session_factory.begin() as database:
            stored = database.get(ShipmentProblemModel, first.id)
            assert stored is not None
            stored.resolved_by = harness.supervisor.user_id
            stored.resolved_at = stored.reported_at - timedelta(seconds=1)


def test_other_problem_requires_description_in_database(
    session_factory: SessionFactory,
) -> None:
    harness = build_shipment_harness(session_factory)
    shipment = harness.create()
    with pytest.raises(IntegrityError):
        with session_factory.begin() as database:
            database.add(
                ShipmentProblemModel(
                    shipment_id=shipment.id,
                    problem_type=ProblemType.OTHER,
                    description=None,
                    previous_status=ShipmentStatus.RECEIVED,
                    reported_by=harness.operator.user_id,
                    reported_at=harness.clock.now(),
                )
            )


def shipment_table():
    from warehouse_control_center.infrastructure.database.models import ShipmentModel

    return ShipmentModel.__table__
