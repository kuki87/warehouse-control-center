"""Phase 4B payment/services persistence, concurrency, audit, and rollback tests."""

import pytest
from sqlalchemy import func, select

from tests.fixtures.shipments import ShipmentHarness, build_shipment_harness
from warehouse_control_center.domain.enums import (
    AdditionalServiceType,
    AuditAction,
    PaymentMethod,
    ShipmentPayer,
)
from warehouse_control_center.domain.exceptions import (
    InvalidShipmentError,
    ShipmentArchivedError,
    ShipmentConflictError,
)
from warehouse_control_center.infrastructure.database.engine import SessionFactory
from warehouse_control_center.infrastructure.database.models import (
    AuditEventModel,
    ShipmentModel,
    ShipmentServiceModel,
)
from warehouse_control_center.infrastructure.database.repositories.audit import (
    SqlAlchemyAuditRepository,
)
from warehouse_control_center.infrastructure.database.repositories.shipments import (
    SqlAlchemyShipmentRepository,
)
from warehouse_control_center.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


@pytest.fixture
def harness(session_factory: SessionFactory) -> ShipmentHarness:
    return build_shipment_harness(session_factory)


def _create_paid(harness: ShipmentHarness):
    return harness.service.create_shipment(
        harness.admin,
        sender_name="Sender",
        recipient_name="Recipient",
        recipient_address="Address",
        recipient_city="City",
        recipient_phone="123",
        declared_value_fen=25_000,
        cod_enabled=True,
        cod_amount_fen=12_500,
        payer=ShipmentPayer.RECIPIENT,
        payment_method=PaymentMethod.CASH,
        services=(AdditionalServiceType.EXPRESS, AdditionalServiceType.INSURANCE),
    )


def _update(harness: ShipmentHarness, shipment, **payment):
    return harness.service.update_shipment(
        harness.admin,
        shipment.id,
        expected_version=shipment.version,
        sender_name=shipment.sender_name,
        recipient_name=shipment.recipient_name,
        recipient_address=shipment.recipient_address,
        recipient_city=shipment.recipient_city,
        recipient_phone=shipment.recipient_phone,
        notes=shipment.notes,
        **payment,
    )


def test_create_persists_exact_payment_services_and_safe_audit(
    harness: ShipmentHarness, session_factory: SessionFactory
) -> None:
    shipment = _create_paid(harness)
    assert shipment.declared_value_fen == 25_000
    assert shipment.cod_enabled and shipment.cod_amount_fen == 12_500
    assert shipment.payer is ShipmentPayer.RECIPIENT
    assert shipment.payment_method is PaymentMethod.CASH
    assert shipment.services == (
        AdditionalServiceType.EXPRESS,
        AdditionalServiceType.INSURANCE,
    )
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(ShipmentServiceModel)) == 2
        event = database.scalar(
            select(AuditEventModel).where(
                AuditEventModel.action == AuditAction.SHIPMENT_CREATED.value
            )
        )
        assert event is not None
        assert event.details_json["cod_amount_fen"] == 12_500
        assert event.details_json["services"] == ["EXPRESS", "INSURANCE"]
        assert "recipient_phone" not in event.details_json


def test_update_can_replace_and_remove_cod_and_services(harness: ShipmentHarness) -> None:
    original = _create_paid(harness)
    updated = _update(
        harness,
        original,
        declared_value_fen=25_000,
        cod_enabled=False,
        cod_amount_fen=None,
        payer=ShipmentPayer.SENDER,
        payment_method=PaymentMethod.ACCOUNT,
        services=(AdditionalServiceType.RETURN_DOCUMENTS,),
    )
    assert not updated.cod_enabled and updated.cod_amount_fen is None
    assert updated.services == (AdditionalServiceType.RETURN_DOCUMENTS,)
    assert updated.version == original.version + 1
    reread = harness.service.get_shipment(harness.operator, original.id)
    assert reread == updated


def test_invalid_insurance_archived_and_stale_updates_are_rejected(
    harness: ShipmentHarness,
) -> None:
    shipment = harness.create()
    with pytest.raises(InvalidShipmentError, match="Insurance"):
        _update(
            harness,
            shipment,
            declared_value_fen=None,
            services=(AdditionalServiceType.INSURANCE,),
        )
    first = _update(
        harness,
        shipment,
        declared_value_fen=100,
        services=(AdditionalServiceType.EXPRESS,),
    )
    with pytest.raises(ShipmentConflictError):
        _update(
            harness,
            shipment,
            declared_value_fen=200,
            services=(AdditionalServiceType.SATURDAY_DELIVERY,),
        )
    archived = harness.service.archive_shipment(
        harness.admin, first.id, expected_version=first.version
    )
    with pytest.raises(ShipmentArchivedError):
        _update(harness, archived, cod_enabled=False, cod_amount_fen=None, services=())


def test_create_and_update_audit_failures_roll_back(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_add = SqlAlchemyAuditRepository.add

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", fail)
    with pytest.raises(RuntimeError, match="audit"):
        _create_paid(harness)
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(ShipmentModel)) == 0
        assert database.scalar(select(func.count()).select_from(ShipmentServiceModel)) == 0

    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", original_add)
    shipment = _create_paid(harness)
    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", fail)
    with pytest.raises(RuntimeError, match="audit"):
        _update(
            harness,
            shipment,
            declared_value_fen=50_000,
            cod_enabled=False,
            cod_amount_fen=None,
            services=(),
        )
    reread = harness.service.get_shipment(harness.operator, shipment.id)
    assert reread.declared_value_fen == 25_000
    assert reread.cod_enabled
    assert len(reread.services) == 2


def test_association_persistence_and_commit_failures_leave_no_partial_rows(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_add = SqlAlchemyShipmentRepository.add

    def fail_after_flush(repository: SqlAlchemyShipmentRepository, shipment):
        original_add(repository, shipment)
        raise RuntimeError("forced association failure")

    monkeypatch.setattr(SqlAlchemyShipmentRepository, "add", fail_after_flush)
    with pytest.raises(RuntimeError, match="association"):
        _create_paid(harness)
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(ShipmentModel)) == 0
        assert database.scalar(select(func.count()).select_from(ShipmentServiceModel)) == 0

    monkeypatch.setattr(SqlAlchemyShipmentRepository, "add", original_add)

    def fail_commit(unit_of_work: SqlAlchemyUnitOfWork) -> None:
        unit_of_work.session.flush()
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(SqlAlchemyUnitOfWork, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="commit"):
        _create_paid(harness)
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(ShipmentModel)) == 0
        assert database.scalar(select(func.count()).select_from(ShipmentServiceModel)) == 0
