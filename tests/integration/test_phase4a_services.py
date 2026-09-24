"""Phase 4A clients, expanded shipments, weighing, concurrency, and rollback."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from tests.fixtures.shipments import ShipmentHarness, build_shipment_harness
from warehouse_control_center.application.permissions import ROLE_PERMISSIONS
from warehouse_control_center.domain.enums import (
    AuditAction,
    Permission,
    UserRole,
    WeightCheckResult,
)
from warehouse_control_center.domain.exceptions import (
    DuplicateClientCodeError,
    InvalidClientStateError,
    InvalidShipmentError,
    PasswordChangeRequiredError,
    PermissionDeniedError,
    ShipmentArchivedError,
)
from warehouse_control_center.infrastructure.database.engine import SessionFactory
from warehouse_control_center.infrastructure.database.models import (
    AuditEventModel,
    ClientModel,
    ShipmentModel,
    ShipmentWeightCheckModel,
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


def _create_client(harness: ShipmentHarness, code: str = "ACME-1"):
    return harness.clients.create_client(
        harness.admin,
        client_code=code,
        company_name="\u017duti \u010cempres d.o.o.",
        tax_id="4400000000000",
        address="Ulica 1",
        city="Sarajevo",
        contact_name="Amila Had\u017ei\u0107",
        phone="+387 61 111 222",
        email="office@example.test",
    )


def test_client_crud_search_duplicate_status_and_permissions(harness: ShipmentHarness) -> None:
    client = _create_client(harness, "  AC ME-1 ")
    assert client.client_code == "AC ME-1"
    assert harness.clients.get_client(harness.operator, client.id) == client
    assert harness.clients.list_clients(harness.operator, search="\u010cempres") == (client,)
    with pytest.raises(DuplicateClientCodeError):
        _create_client(harness, "acme-1")
    with pytest.raises(PasswordChangeRequiredError):
        harness.clients.list_clients(replace(harness.operator, must_change_password=True))

    updated = harness.clients.update_client(
        harness.admin,
        client.id,
        client_code=client.client_code,
        company_name="Nova kompanija",
        tax_id=client.tax_id,
        address=client.address,
        city="Mostar",
        contact_name=client.contact_name,
        phone=client.phone,
        email=client.email,
        contract_number=None,
        contract_start=None,
        contract_end=None,
        notes="Updated",
    )
    assert updated.company_name == "Nova kompanija"
    inactive = harness.clients.deactivate_client(harness.admin, client.id)
    assert not inactive.active
    assert harness.clients.list_clients(harness.operator, active_only=True) == ()
    with pytest.raises(InvalidClientStateError):
        harness.service.create_shipment(
            harness.operator,
            sender_name=None,
            sender_client_id=client.id,
            recipient_name="Recipient",
            recipient_address="Address",
            recipient_city="City",
            recipient_phone="123",
        )
    assert harness.clients.activate_client(harness.admin, client.id).active


def test_expanded_shipment_uses_client_snapshot_and_exact_measurements(
    harness: ShipmentHarness,
) -> None:
    client = _create_client(harness)
    shipment = harness.service.create_shipment(
        harness.operator,
        sender_name="ignored",
        sender_client_id=client.id,
        recipient_name="Recipient",
        recipient_address="Address",
        recipient_city="City",
        recipient_phone="123",
        package_count=3,
        length_cm=Decimal("10.2"),
        width_cm="20",
        height_cm=30,
        declared_weight_g=10_250,
    )
    assert shipment.sender_client_id == client.id
    assert shipment.sender_name == client.company_name
    assert shipment.package_count == 3
    assert (shipment.length_cm, shipment.width_cm, shipment.height_cm) == (
        Decimal("10.2"),
        Decimal("20"),
        Decimal("30"),
    )
    assert shipment.declared_weight_g == 10_250

    legacy_defaults = harness.create()
    assert legacy_defaults.package_count == 1
    assert legacy_defaults.sender_client_id is None
    assert legacy_defaults.declared_weight_g is None


def test_control_weight_is_append_only_ordered_audited_and_does_not_bump_version(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    shipment = harness.service.create_shipment(
        harness.admin,
        sender_name="Sender",
        recipient_name="Recipient",
        recipient_address="Address",
        recipient_city="City",
        recipient_phone="123",
        declared_weight_g=1_000,
    )
    first = harness.service.record_control_weight(
        harness.operator, shipment.id, measured_weight_g=1_100, note="Boundary"
    )
    harness.clock.advance(seconds=1)
    second = harness.service.record_control_weight(
        harness.supervisor, shipment.id, measured_weight_g=1_101
    )
    assert first.result is WeightCheckResult.UNDER_TOLERANCE
    assert second.result is WeightCheckResult.OVER_TOLERANCE
    assert first.declared_weight_g_snapshot == second.declared_weight_g_snapshot == 1_000
    assert harness.service.get_weight_checks(harness.operator, shipment.id) == (first, second)
    assert harness.service.get_shipment(harness.admin, shipment.id).version == shipment.version
    with session_factory() as database:
        event = database.scalar(
            select(AuditEventModel)
            .where(AuditEventModel.action == AuditAction.SHIPMENT_WEIGHT_CHECKED.value)
            .order_by(AuditEventModel.id.desc())
        )
        assert event is not None
        assert event.details_json == {
            "shipment_number": shipment.shipment_number,
            "measured_weight_g": 1_101,
            "result": WeightCheckResult.OVER_TOLERANCE.value,
        }


def test_control_weight_rejects_missing_declared_archived_invalid_and_restricted(
    harness: ShipmentHarness,
) -> None:
    no_declared = harness.create()
    with pytest.raises(InvalidShipmentError, match="declared weight"):
        harness.service.record_control_weight(
            harness.operator, no_declared.id, measured_weight_g=1_000
        )
    with pytest.raises(InvalidShipmentError):
        harness.service.record_control_weight(harness.operator, no_declared.id, measured_weight_g=0)
    weighted = harness.service.create_shipment(
        harness.admin,
        sender_name="Sender",
        recipient_name="Recipient",
        recipient_address="Address",
        recipient_city="City",
        recipient_phone="123",
        declared_weight_g=1_000,
    )
    archived = harness.service.archive_shipment(
        harness.admin, weighted.id, expected_version=weighted.version
    )
    with pytest.raises(ShipmentArchivedError):
        harness.service.record_control_weight(
            harness.operator, archived.id, measured_weight_g=1_000
        )
    with pytest.raises(PasswordChangeRequiredError):
        harness.service.record_control_weight(
            replace(harness.operator, must_change_password=True),
            weighted.id,
            measured_weight_g=1_000,
        )


def test_control_weight_requires_explicit_permission(
    harness: ShipmentHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipment = harness.service.create_shipment(
        harness.admin,
        sender_name="Sender",
        recipient_name="Recipient",
        recipient_address="Address",
        recipient_city="City",
        recipient_phone="123",
        declared_weight_g=1_000,
    )
    operator_permissions = ROLE_PERMISSIONS[UserRole.WAREHOUSE_OPERATOR]
    monkeypatch.setitem(
        ROLE_PERMISSIONS,
        UserRole.WAREHOUSE_OPERATOR,
        operator_permissions - {Permission.CONTROL_WEIGHT_SHIPMENT},
    )
    with pytest.raises(PermissionDeniedError):
        harness.service.record_control_weight(
            harness.operator, shipment.id, measured_weight_g=1_000
        )


def test_concurrent_weight_checks_are_both_preserved(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    shipment = harness.service.create_shipment(
        harness.admin,
        sender_name="Sender",
        recipient_name="Recipient",
        recipient_address="Address",
        recipient_city="City",
        recipient_phone="123",
        declared_weight_g=1_000,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        checks = list(
            executor.map(
                lambda value: harness.service.record_control_weight(
                    harness.operator, shipment.id, measured_weight_g=value
                ),
                (990, 1_010),
            )
        )
    assert len({check.id for check in checks}) == 2
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(ShipmentWeightCheckModel)) == 2


def test_client_and_weight_audit_failures_roll_back(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced failure")

    original_audit = SqlAlchemyAuditRepository.add
    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", fail)
    with pytest.raises(RuntimeError, match="forced"):
        _create_client(harness)
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(ClientModel)) == 0

    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", original_audit)
    shipment = harness.service.create_shipment(
        harness.admin,
        sender_name="Sender",
        recipient_name="Recipient",
        recipient_address="Address",
        recipient_city="City",
        recipient_phone="123",
        declared_weight_g=1_000,
    )
    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", fail)
    with pytest.raises(RuntimeError, match="forced"):
        harness.service.record_control_weight(
            harness.operator, shipment.id, measured_weight_g=1_000
        )
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(ShipmentWeightCheckModel)) == 0


def test_shipment_with_client_relation_rolls_back_when_audit_fails(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _create_client(harness)

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", fail)
    with pytest.raises(RuntimeError, match="audit"):
        harness.service.create_shipment(
            harness.operator,
            sender_name=None,
            sender_client_id=client.id,
            recipient_name="Recipient",
            recipient_address="Address",
            recipient_city="City",
            recipient_phone="123",
        )
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(ShipmentModel)) == 0


def test_persistence_and_commit_failures_leave_no_partial_weight_check(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shipment = harness.service.create_shipment(
        harness.admin,
        sender_name="Sender",
        recipient_name="Recipient",
        recipient_address="Address",
        recipient_city="City",
        recipient_phone="123",
        declared_weight_g=1_000,
    )

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced failure")

    monkeypatch.setattr(SqlAlchemyShipmentRepository, "add_weight_check", fail)
    with pytest.raises(RuntimeError, match="forced"):
        harness.service.record_control_weight(
            harness.operator, shipment.id, measured_weight_g=1_000
        )
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(ShipmentWeightCheckModel)) == 0


def test_client_create_commit_failure_rolls_back_client_and_audit(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_after_flush(unit_of_work: SqlAlchemyUnitOfWork) -> None:
        unit_of_work.session.flush()
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(SqlAlchemyUnitOfWork, "commit", fail_after_flush)
    with pytest.raises(RuntimeError, match="commit"):
        _create_client(harness)
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(ClientModel)) == 0


def test_weight_check_commit_failure_rolls_back_history_and_audit(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shipment = harness.service.create_shipment(
        harness.admin,
        sender_name="Sender",
        recipient_name="Recipient",
        recipient_address="Address",
        recipient_city="City",
        recipient_phone="123",
        declared_weight_g=1_000,
    )

    def fail_after_flush(unit_of_work: SqlAlchemyUnitOfWork) -> None:
        unit_of_work.session.flush()
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(SqlAlchemyUnitOfWork, "commit", fail_after_flush)
    with pytest.raises(RuntimeError, match="commit"):
        harness.service.record_control_weight(
            harness.operator, shipment.id, measured_weight_g=1_050
        )
    with session_factory() as database:
        assert database.scalar(select(func.count()).select_from(ShipmentWeightCheckModel)) == 0
        assert (
            database.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(AuditEventModel.action == AuditAction.SHIPMENT_WEIGHT_CHECKED.value)
            )
            == 0
        )
