"""Phase 4C SMS authorization, history, query, concurrency, and rollback tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from tests.fixtures.shipments import ShipmentHarness, build_shipment_harness
from warehouse_control_center.application.permissions import ROLE_PERMISSIONS
from warehouse_control_center.domain.enums import (
    AuditAction,
    Permission,
    SmsMessageType,
    SmsSenderType,
    SmsSendStatus,
    UserRole,
)
from warehouse_control_center.domain.exceptions import (
    PermissionDeniedError,
    ShipmentArchivedError,
)
from warehouse_control_center.infrastructure.database.engine import SessionFactory
from warehouse_control_center.infrastructure.database.models import (
    AuditEventModel,
    ShipmentSmsEventModel,
)
from warehouse_control_center.infrastructure.database.repositories.audit import (
    SqlAlchemyAuditRepository,
)
from warehouse_control_center.infrastructure.database.repositories.shipment_sms import (
    SqlAlchemyShipmentSmsRepository,
)
from warehouse_control_center.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


@pytest.fixture
def harness(session_factory: SessionFactory) -> ShipmentHarness:
    return build_shipment_harness(session_factory)


def _record(
    harness: ShipmentHarness,
    shipment_id: int,
    *,
    sender_type: SmsSenderType = SmsSenderType.WAREHOUSE,
    message_type: SmsMessageType = SmsMessageType.CUSTOM,
    message_text: str | None = "Recorded message",
):
    return harness.sms.record_sms(
        harness.operator,
        shipment_id,
        sender_type=sender_type,
        message_type=message_type,
        message_text=message_text,
    )


def test_record_sender_types_default_phone_template_and_safe_audit(
    harness: ShipmentHarness, session_factory: SessionFactory
) -> None:
    shipment = harness.create()
    warehouse = _record(harness, shipment.id)
    courier = _record(harness, shipment.id, sender_type=SmsSenderType.COURIER)
    system = _record(
        harness,
        shipment.id,
        sender_type=SmsSenderType.SYSTEM,
        message_type=SmsMessageType.READY_FOR_PICKUP,
        message_text=None,
    )
    assert warehouse.phone_number == shipment.recipient_phone
    assert warehouse.sent_by_user_id == harness.operator.user_id
    assert courier.sent_by_user_id == harness.operator.user_id
    assert system.sent_by_user_id is None
    assert shipment.shipment_number in system.message_text
    with session_factory() as database:
        events = database.scalars(
            select(AuditEventModel).where(
                AuditEventModel.action == AuditAction.SHIPMENT_SMS_RECORDED.value
            )
        ).all()
        assert len(events) == 3
        assert all("message_text" not in event.details_json for event in events)
        assert events[-1].details_json["send_status"] == "RECORDED"


def test_archived_permission_and_stale_actor_are_rejected(
    harness: ShipmentHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment = harness.create()
    archived = harness.service.archive_shipment(
        harness.admin, shipment.id, expected_version=shipment.version
    )
    with pytest.raises(ShipmentArchivedError):
        _record(harness, archived.id)

    active = harness.create(recipient_name="Second")
    monkeypatch.setitem(
        ROLE_PERMISSIONS,
        UserRole.WAREHOUSE_OPERATOR,
        frozenset({Permission.VIEW_SHIPMENTS, Permission.VIEW_SHIPMENT_SMS}),
    )
    with pytest.raises(PermissionDeniedError):
        _record(harness, active.id)
    stale = replace(harness.admin, credential_version=999)
    with pytest.raises(PermissionDeniedError):
        harness.sms.list_sms_for_shipment(stale, active.id)


def test_history_is_append_only_ordered_and_snapshots_survive_shipment_update(
    harness: ShipmentHarness,
) -> None:
    shipment = harness.create(recipient_phone="+387 61 111 111")
    first = _record(harness, shipment.id, message_text="Prva poruka")
    harness.clock.advance(seconds=1)
    second = _record(harness, shipment.id, message_text="Druga poruka")
    harness.service.update_shipment(
        harness.admin,
        shipment.id,
        expected_version=shipment.version,
        sender_name=shipment.sender_name,
        recipient_name=shipment.recipient_name,
        recipient_address=shipment.recipient_address,
        recipient_city=shipment.recipient_city,
        recipient_phone="+387 62 222 222",
        notes=shipment.notes,
    )
    page = harness.sms.list_sms_for_shipment(harness.operator, shipment.id)
    assert page.total == 2
    assert [event.id for event in page.items] == [second.id, first.id]
    assert {event.phone_number for event in page.items} == {"+387 61 111 111"}
    assert [event.message_text for event in page.items] == ["Druga poruka", "Prva poruka"]


def test_shipments_page_counts_latest_filters_paginates_and_excludes_no_sms(
    harness: ShipmentHarness,
) -> None:
    first = harness.create(recipient_name="Alpha", recipient_city="Mostar")
    second = harness.create(recipient_name="Beta", recipient_city="Sarajevo")
    harness.create(recipient_name="No SMS")
    _record(harness, first.id, message_text="first")
    harness.clock.advance(seconds=1)
    _record(
        harness,
        first.id,
        sender_type=SmsSenderType.COURIER,
        message_type=SmsMessageType.DELIVERY_ATTEMPT,
        message_text="latest",
    )
    harness.clock.advance(seconds=1)
    _record(harness, second.id, message_text="other")

    page = harness.sms.list_shipments_with_sms(harness.operator, page=1, page_size=1)
    assert page.total == 2 and len(page.items) == 1
    assert page.items[0].shipment.id == second.id
    searched = harness.sms.list_shipments_with_sms(harness.operator, search="Alpha")
    assert searched.total == 1
    assert searched.items[0].sms_count == 2
    assert searched.items[0].last_event.message_text == "latest"
    filtered = harness.sms.list_shipments_with_sms(
        harness.operator,
        sender_type=SmsSenderType.COURIER,
        message_type=SmsMessageType.DELIVERY_ATTEMPT,
        send_status=SmsSendStatus.RECORDED,
    )
    assert filtered.total == 1
    assert filtered.items[0].sms_count == 1


def test_two_concurrent_events_are_both_preserved(
    harness: ShipmentHarness, session_factory: SessionFactory
) -> None:
    shipment = harness.create()

    def record(text: str) -> None:
        harness.sms.record_sms(
            harness.operator,
            shipment.id,
            sender_type=SmsSenderType.WAREHOUSE,
            message_type=SmsMessageType.CUSTOM,
            message_text=text,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(record, ("one", "two")))
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(ShipmentSmsEventModel)) == 2
    current = harness.service.get_shipment(harness.operator, shipment.id)
    assert current.version == shipment.version


def test_sms_persistence_audit_and_commit_failures_roll_back(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shipment = harness.create()

    original_add = SqlAlchemyShipmentSmsRepository.add

    def fail_sms(repository: SqlAlchemyShipmentSmsRepository, event: object) -> None:
        original_add(repository, event)  # type: ignore[arg-type]
        raise RuntimeError("forced SMS persistence failure")

    monkeypatch.setattr(SqlAlchemyShipmentSmsRepository, "add", fail_sms)
    with pytest.raises(RuntimeError, match="persistence"):
        _record(harness, shipment.id)
    monkeypatch.undo()

    def fail_audit(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", fail_audit)
    with pytest.raises(RuntimeError, match="audit"):
        _record(harness, shipment.id)
    monkeypatch.undo()

    def fail_commit(unit_of_work: SqlAlchemyUnitOfWork) -> None:
        unit_of_work.session.flush()
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(SqlAlchemyUnitOfWork, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="commit"):
        _record(harness, shipment.id)
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(ShipmentSmsEventModel)) == 0


def test_sms_database_foreign_keys_reject_unknown_shipment_and_user(
    harness: ShipmentHarness, session_factory: SessionFactory
) -> None:
    shipment = harness.create()
    statement = text(
        "INSERT INTO shipment_sms_events "
        "(shipment_id, sender_type, sent_by_user_id, phone_number, message_type, "
        "message_text, send_status, sent_at) VALUES "
        "(:shipment_id, 'WAREHOUSE', :user_id, '123', 'CUSTOM', 'SMS', "
        "'RECORDED', CURRENT_TIMESTAMP)"
    )
    with session_factory.begin() as database, pytest.raises(IntegrityError):
        database.execute(statement, {"shipment_id": 999_999, "user_id": harness.admin.user_id})
    with session_factory.begin() as database, pytest.raises(IntegrityError):
        database.execute(statement, {"shipment_id": shipment.id, "user_id": 999_999})
