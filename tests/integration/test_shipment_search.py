"""Shipment query foundation uses bounded database pagination and indexed exact lookup."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select, text

from tests.fixtures.shipments import ShipmentHarness, build_shipment_harness
from warehouse_control_center.application.services.shipments import MAX_PAGE_SIZE
from warehouse_control_center.domain.enums import ProblemType, ShipmentStatus
from warehouse_control_center.domain.exceptions import InvalidShipmentQueryError
from warehouse_control_center.infrastructure.database.engine import SessionFactory
from warehouse_control_center.infrastructure.database.models import CourierModel, ShipmentModel


@pytest.fixture
def harness(session_factory: SessionFactory) -> ShipmentHarness:
    return build_shipment_harness(session_factory)


def test_exact_lookup_and_partial_search_fields(harness: ShipmentHarness) -> None:
    shipment = harness.create(
        tracking_number=" BA-ABC-123 ",
        barcode=" PKG-9001 ",
        recipient_name="Amila Hadžić",
        recipient_address="Trg oslobođenja 7",
        recipient_phone="+387 61 555 222",
    )

    assert harness.service.get_by_tracking_number(harness.operator, "BA-ABC-123").id == shipment.id
    assert harness.service.get_by_barcode(harness.operator, "pkg-9001").id == shipment.id
    for term in ("Amila", "555 222", "oslobođenja", "ABC-123"):
        result = harness.service.list_shipments(harness.operator, search=term)
        assert [item.id for item in result.items] == [shipment.id]


def test_filters_sorting_pagination_and_archived_inclusion(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    first = harness.create(recipient_name="Zoran", recipient_city="Sarajevo")
    harness.clock.advance(days=1)
    second = harness.create(recipient_name="Amila", recipient_city="Mostar")
    harness.clock.advance(days=1)
    third = harness.create(recipient_name="Branko", recipient_city="Mostar")
    with session_factory.begin() as database:
        courier = CourierModel(
            courier_code="C-1",
            courier_code_normalized="c-1",
            first_name="Courier",
            last_name="One",
        )
        database.add(courier)
        database.flush()
        second_model = database.get(ShipmentModel, second.id)
        third_model = database.get(ShipmentModel, third.id)
        assert second_model is not None and third_model is not None
        second_model.status = ShipmentStatus.SORTING
        second_model.courier_id = courier.id
        third_model.status = ShipmentStatus.SORTING
        third_model.archived_at = harness.clock.now()

    filtered = harness.service.list_shipments(
        harness.admin,
        city="Mostar",
        status=ShipmentStatus.SORTING,
        courier_id=courier.id,
        date_from=first.received_at + timedelta(hours=12),
        date_to=third.received_at + timedelta(hours=12),
        sort_by="recipient_name",
        sort_direction="asc",
    )
    assert [item.id for item in filtered.items] == [second.id]
    included = harness.service.list_shipments(
        harness.admin,
        status=ShipmentStatus.SORTING,
        include_archived=True,
        sort_by="recipient_name",
        sort_direction="asc",
    )
    assert [item.id for item in included.items] == [second.id, third.id]

    page_one = harness.service.list_shipments(
        harness.admin,
        page=1,
        page_size=1,
        include_archived=True,
        sort_by="tracking_number",
        sort_direction="asc",
    )
    page_two = harness.service.list_shipments(
        harness.admin,
        page=2,
        page_size=1,
        include_archived=True,
        sort_by="tracking_number",
        sort_direction="asc",
    )
    assert page_one.total == 3
    assert len(page_one.items) == len(page_two.items) == 1
    assert page_one.items[0].id != page_two.items[0].id
    beyond_end = harness.service.list_shipments(
        harness.admin,
        page=99,
        page_size=MAX_PAGE_SIZE,
        include_archived=True,
    )
    assert beyond_end.total == 3
    assert beyond_end.items == ()
    no_results = harness.service.list_shipments(harness.admin, search="does-not-exist")
    assert no_results.total == 0
    assert no_results.items == ()


def test_problem_only_filter_returns_only_open_problems(harness: ShipmentHarness) -> None:
    problem_shipment = harness.create()
    normal_shipment = harness.create()
    harness.service.report_problem(
        harness.operator,
        problem_shipment.id,
        ProblemType.DAMAGED,
        expected_version=problem_shipment.version,
    )

    result = harness.service.list_shipments(harness.admin, problem_only=True)
    assert [item.id for item in result.items] == [problem_shipment.id]
    assert normal_shipment.id not in {item.id for item in result.items}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": MAX_PAGE_SIZE + 1},
        {"sort_by": "DROP TABLE shipments"},
        {"sort_direction": "sideways"},
        {"courier_id": -1},
        {"date_from": datetime(2026, 1, 2)},
        {
            "date_from": datetime(2026, 1, 2, tzinfo=UTC),
            "date_to": datetime(2026, 1, 1, tzinfo=UTC),
        },
    ],
)
def test_invalid_query_inputs_are_rejected(
    harness: ShipmentHarness,
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(InvalidShipmentQueryError):
        harness.service.list_shipments(harness.admin, **kwargs)  # type: ignore[arg-type]


def test_ten_thousand_row_pagination_and_query_plans_are_indexed(
    harness: ShipmentHarness,
    engine: Engine,
) -> None:
    now = harness.clock.now()
    rows = [
        {
            "tracking_number": f"PERF-{index:05d}",
            "tracking_number_normalized": f"PERF-{index:05d}",
            "barcode": f"PERF-BAR-{index:05d}",
            "barcode_normalized": f"PERF-BAR-{index:05d}",
            "recipient_name": f"Recipient {index}",
            "recipient_address": f"Address {index}",
            "recipient_city": "Mostar" if index % 2 else "Sarajevo",
            "recipient_phone": f"+387 61 {index:05d}",
            "sender_name": "Performance Sender",
            "status": ShipmentStatus.RECEIVED,
            "received_at": now,
            "created_at": now,
            "updated_at": now,
            "created_by": harness.admin.user_id,
            "version": 1,
        }
        for index in range(10_000)
    ]
    with engine.begin() as connection:
        connection.execute(ShipmentModel.__table__.insert(), rows)

    page = harness.service.list_shipments(
        harness.admin,
        page=100,
        page_size=50,
        status=ShipmentStatus.RECEIVED,
    )
    assert page.total == 10_000
    assert len(page.items) == 50

    with engine.connect() as connection:
        plans = {
            "tracking": connection.exec_driver_sql(
                "EXPLAIN QUERY PLAN SELECT id FROM shipments WHERE tracking_number_normalized = ?",
                ("PERF-05000",),
            ).all(),
            "barcode": connection.exec_driver_sql(
                "EXPLAIN QUERY PLAN SELECT id FROM shipments WHERE barcode_normalized = ?",
                ("PERF-BAR-05000",),
            ).all(),
            "status": connection.execute(
                text(
                    "EXPLAIN QUERY PLAN SELECT id FROM shipments "
                    "WHERE status = 'RECEIVED' LIMIT 50 OFFSET 4950"
                )
            ).all(),
        }
    for label, rows_for_plan in plans.items():
        rendered = " ".join(str(value) for row in rows_for_plan for value in row).upper()
        assert "INDEX" in rendered, (label, rendered)

    with engine.connect() as connection:
        assert connection.scalar(select(ShipmentModel.id).limit(1)) is not None
