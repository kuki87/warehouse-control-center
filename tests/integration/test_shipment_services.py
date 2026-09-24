"""Phase 3A shipment creation, workflow, problem, archive, and concurrency tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest
from sqlalchemy import func, select

from tests.fixtures.shipments import ShipmentHarness, build_shipment_harness
from warehouse_control_center.application.dto import SessionContext
from warehouse_control_center.domain.enums import AuditAction, ProblemType, ShipmentStatus, UserRole
from warehouse_control_center.domain.exceptions import (
    InvalidShipmentError,
    InvalidShipmentTransitionError,
    PermissionDeniedError,
    ShipmentArchivedError,
    ShipmentConflictError,
    ShipmentProblemNotFoundError,
    ShipmentProblemOpenError,
)
from warehouse_control_center.infrastructure.database.engine import SessionFactory
from warehouse_control_center.infrastructure.database.models import (
    AuditEventModel,
    ShipmentModel,
    ShipmentNumberSequenceModel,
    ShipmentProblemModel,
    ShipmentStatusHistoryModel,
    UserModel,
)
from warehouse_control_center.infrastructure.database.repositories.shipments import (
    SqlAlchemyShipmentRepository,
)
from warehouse_control_center.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


@pytest.fixture
def harness(session_factory: SessionFactory) -> ShipmentHarness:
    return build_shipment_harness(session_factory)


def _count(session_factory: SessionFactory, model: type[object]) -> int:
    with session_factory() as database:
        return database.scalar(select(func.count()).select_from(model)) or 0


def _audit_actions(session_factory: SessionFactory) -> list[str]:
    with session_factory() as database:
        return list(database.scalars(select(AuditEventModel.action).order_by(AuditEventModel.id)))


def _set_status(
    session_factory: SessionFactory,
    shipment_id: int,
    status: ShipmentStatus,
    *,
    archived_at: datetime | None = None,
) -> int:
    with session_factory.begin() as database:
        model = database.get(ShipmentModel, shipment_id)
        assert model is not None
        model.status = status
        model.archived_at = archived_at
    with session_factory() as database:
        model = database.get(ShipmentModel, shipment_id)
        assert model is not None
        return model.version


def test_create_shipment_sets_received_state_and_atomic_audit(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    shipment = harness.create(session=harness.operator, notes="Fragile")

    assert shipment.status is ShipmentStatus.RECEIVED
    assert shipment.received_at == harness.clock.now()
    assert shipment.created_by == harness.operator.user_id
    assert shipment.version == 1
    assert shipment.notes == "Fragile"
    assert _count(session_factory, ShipmentStatusHistoryModel) == 0
    with session_factory() as database:
        event = database.scalar(
            select(AuditEventModel).where(
                AuditEventModel.action == AuditAction.SHIPMENT_CREATED.value
            )
        )
        assert event is not None
        assert event.entity_type == "SHIPMENT"
        assert event.details_json == {"shipment_number": shipment.shipment_number}


def test_creation_allocates_sequential_shipment_numbers(
    harness: ShipmentHarness,
) -> None:
    first = harness.create()
    second = harness.create()

    assert first.shipment_number == "E000000001"
    assert second.shipment_number == "E000000002"


def test_all_shipment_audit_payloads_use_only_the_canonical_identifier(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    created = harness.create()
    updated = harness.service.update_shipment(
        harness.supervisor,
        created.id,
        expected_version=created.version,
        recipient_name=created.recipient_name,
        recipient_address=created.recipient_address,
        recipient_city=created.recipient_city,
        recipient_phone=created.recipient_phone,
        sender_name=created.sender_name,
        notes="Updated",
    )
    sorting = harness.service.change_status(
        harness.operator,
        created.id,
        ShipmentStatus.SORTING,
        expected_version=updated.version,
    ).shipment
    harness.service.report_problem(
        harness.operator,
        created.id,
        ProblemType.DAMAGED,
        expected_version=sorting.version,
    )
    in_problem = harness.service.get_shipment(harness.admin, created.id)
    harness.service.resolve_problem(
        harness.supervisor,
        created.id,
        expected_version=in_problem.version,
    )
    resolved = harness.service.get_shipment(harness.admin, created.id)
    archived = harness.service.archive_shipment(
        harness.admin,
        created.id,
        expected_version=resolved.version,
    )
    harness.service.restore_shipment(
        harness.admin,
        created.id,
        expected_version=archived.version,
    )

    with session_factory() as database:
        events = list(
            database.scalars(
                select(AuditEventModel)
                .where(AuditEventModel.entity_type == "SHIPMENT")
                .order_by(AuditEventModel.id)
            )
        )
    assert len(events) == 7
    for event in events:
        assert event.details_json["shipment_number"] == created.shipment_number
        assert "tracking_number" not in event.details_json
        assert "barcode" not in event.details_json


def test_missing_inactive_and_forged_actor_sessions_are_rejected(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    missing = replace(harness.admin, user_id=999_999)
    with pytest.raises(PermissionDeniedError, match="no longer authorized"):
        harness.create(session=missing)

    with session_factory.begin() as database:
        actor = database.get(UserModel, harness.operator.user_id)
        assert actor is not None
        actor.active = False
    with pytest.raises(PermissionDeniedError, match="no longer authorized"):
        harness.create(session=harness.operator)

    forged = SessionContext(
        user_id=harness.supervisor.user_id,
        username=harness.supervisor.username,
        role=UserRole.ADMIN,
        authenticated_at=harness.supervisor.authenticated_at,
        credential_version=harness.supervisor.credential_version,
    )
    shipment = harness.create()
    with pytest.raises(PermissionDeniedError, match="no longer authorized"):
        harness.service.archive_shipment(forged, shipment.id, expected_version=shipment.version)


def test_stale_credential_and_archived_actor_sessions_are_rejected(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    shipment = harness.create()
    stale = replace(
        harness.admin,
        credential_version=harness.admin.credential_version + 1,
    )
    with pytest.raises(PermissionDeniedError, match="no longer authorized"):
        harness.service.archive_shipment(
            stale,
            shipment.id,
            expected_version=shipment.version,
        )

    with session_factory.begin() as database:
        actor = database.get(UserModel, harness.admin.user_id)
        assert actor is not None
        actor.archived_at = harness.clock.now()
    with pytest.raises(PermissionDeniedError, match="no longer authorized"):
        harness.service.archive_shipment(
            harness.admin,
            shipment.id,
            expected_version=shipment.version,
        )


def test_update_validates_metadata_permissions_archive_and_version(
    harness: ShipmentHarness,
) -> None:
    shipment = harness.create()
    with pytest.raises(PermissionDeniedError):
        harness.service.update_shipment(
            harness.operator,
            shipment.id,
            expected_version=shipment.version,
            recipient_name="New",
            recipient_address="Address",
            recipient_city="City",
            recipient_phone="123",
            sender_name="Sender",
            notes=None,
        )

    updated = harness.service.update_shipment(
        harness.supervisor,
        shipment.id,
        expected_version=shipment.version,
        recipient_name="Čedomir Žugić",
        recipient_address="Ulica šljiva 5",
        recipient_city="Čačak",
        recipient_phone="+381 11 234-567",
        sender_name="Špedicija Đurić",
        notes="Ažurirano",
    )
    assert updated.recipient_name == "Čedomir Žugić"
    assert updated.status is ShipmentStatus.RECEIVED
    assert updated.courier_id is None
    assert updated.version == shipment.version + 1

    with pytest.raises(ShipmentConflictError):
        harness.service.update_shipment(
            harness.supervisor,
            shipment.id,
            expected_version=shipment.version,
            recipient_name="Stale",
            recipient_address="Address",
            recipient_city="City",
            recipient_phone="123",
            sender_name="Sender",
            notes=None,
        )


def test_update_rejects_empty_overlong_and_archived_metadata(
    harness: ShipmentHarness,
) -> None:
    shipment = harness.create()
    for invalid_name in (" ", "x" * 256):
        with pytest.raises(InvalidShipmentError):
            harness.service.update_shipment(
                harness.supervisor,
                shipment.id,
                expected_version=shipment.version,
                recipient_name=invalid_name,
                recipient_address=shipment.recipient_address,
                recipient_city=shipment.recipient_city,
                recipient_phone=shipment.recipient_phone,
                sender_name=shipment.sender_name,
                notes=shipment.notes,
            )

    archived = harness.service.archive_shipment(
        harness.admin,
        shipment.id,
        expected_version=shipment.version,
    )
    with pytest.raises(ShipmentArchivedError):
        harness.service.update_shipment(
            harness.supervisor,
            shipment.id,
            expected_version=archived.version,
            recipient_name="Cannot change",
            recipient_address=shipment.recipient_address,
            recipient_city=shipment.recipient_city,
            recipient_phone=shipment.recipient_phone,
            sender_name=shipment.sender_name,
            notes=shipment.notes,
        )


def test_two_independent_units_of_work_detect_optimistic_conflict(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    created = harness.create()
    first = SqlAlchemyUnitOfWork(session_factory)
    second = SqlAlchemyUnitOfWork(session_factory)
    with first, second:
        left = first.shipments.get_by_id(created.id)
        right = second.shipments.get_by_id(created.id)
        assert left is not None and right is not None
        left.notes = "first writer"
        right.notes = "stale writer"
        first.shipments.save(left)
        first.commit()
        with pytest.raises(ShipmentConflictError):
            second.shipments.save(right)

    assert harness.service.get_shipment(harness.admin, created.id).notes == "first writer"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ShipmentStatus.RECEIVED, ShipmentStatus.SORTING),
        (ShipmentStatus.SORTING, ShipmentStatus.READY_FOR_COURIER),
        (ShipmentStatus.READY_FOR_COURIER, ShipmentStatus.ASSIGNED),
        (ShipmentStatus.ASSIGNED, ShipmentStatus.DISPATCHED),
        (ShipmentStatus.ASSIGNED, ShipmentStatus.READY_FOR_COURIER),
        (ShipmentStatus.DISPATCHED, ShipmentStatus.RETURNED),
        (ShipmentStatus.RETURNED, ShipmentStatus.SORTING),
    ],
)
def test_every_allowed_status_transition_persists_history_and_audit(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    current: ShipmentStatus,
    target: ShipmentStatus,
) -> None:
    shipment = harness.create()
    version = _set_status(session_factory, shipment.id, current)
    result = harness.service.change_status(
        harness.operator,
        shipment.id,
        target,
        expected_version=version,
        reason="workflow test",
    )

    assert result.changed
    assert result.shipment.status is target
    history = harness.service.get_status_history(harness.operator, shipment.id)
    assert [(item.old_status, item.new_status) for item in history] == [(current, target)]
    assert _audit_actions(session_factory)[-1] == AuditAction.SHIPMENT_STATUS_CHANGED.value


@pytest.mark.parametrize(
    "current",
    [
        ShipmentStatus.RECEIVED,
        ShipmentStatus.SORTING,
        ShipmentStatus.READY_FOR_COURIER,
        ShipmentStatus.ASSIGNED,
        ShipmentStatus.RETURNED,
    ],
)
def test_every_problem_transition_uses_problem_record_path(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    current: ShipmentStatus,
) -> None:
    shipment = harness.create()
    version = _set_status(session_factory, shipment.id, current)
    with pytest.raises(InvalidShipmentTransitionError, match="report_problem"):
        harness.service.change_status(
            harness.operator,
            shipment.id,
            ShipmentStatus.PROBLEM,
            expected_version=version,
        )
    problem = harness.service.report_problem(
        harness.operator,
        shipment.id,
        ProblemType.DAMAGED,
        expected_version=version,
    )
    assert problem.previous_status is current


def test_idempotent_status_change_creates_no_history_audit_or_timestamp_change(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    shipment = harness.create()
    before_audits = _count(session_factory, AuditEventModel)
    result = harness.service.change_status(
        harness.operator,
        shipment.id,
        ShipmentStatus.RECEIVED,
        expected_version=shipment.version,
    )

    assert not result.changed
    assert result.shipment.version == shipment.version
    assert result.shipment.updated_at == shipment.updated_at
    assert _count(session_factory, ShipmentStatusHistoryModel) == 0
    assert _count(session_factory, AuditEventModel) == before_audits


def test_invalid_status_requires_authorized_reasoned_override(
    harness: ShipmentHarness,
) -> None:
    shipment = harness.create()
    with pytest.raises(InvalidShipmentTransitionError):
        harness.service.change_status(
            harness.operator,
            shipment.id,
            ShipmentStatus.DISPATCHED,
            expected_version=shipment.version,
        )
    with pytest.raises(InvalidShipmentError, match="override reason"):
        harness.service.change_status(
            harness.admin,
            shipment.id,
            ShipmentStatus.DISPATCHED,
            expected_version=shipment.version,
            override=True,
        )
    with pytest.raises(PermissionDeniedError):
        harness.service.change_status(
            harness.operator,
            shipment.id,
            ShipmentStatus.DISPATCHED,
            expected_version=shipment.version,
            reason="operator cannot override",
            override=True,
        )

    changed = harness.service.change_status(
        harness.admin,
        shipment.id,
        ShipmentStatus.DISPATCHED,
        expected_version=shipment.version,
        reason="Emergency manual correction",
        override=True,
    )
    history = harness.service.get_status_history(harness.admin, shipment.id)
    assert changed.shipment.status is ShipmentStatus.DISPATCHED
    assert history[0].is_admin_override
    assert history[0].reason == "Emergency manual correction"


def test_summary_timestamps_are_set_once_and_never_erased(
    harness: ShipmentHarness,
) -> None:
    shipment = harness.create()
    harness.clock.advance(minutes=1)
    sorting = harness.service.change_status(
        harness.operator,
        shipment.id,
        ShipmentStatus.SORTING,
        expected_version=shipment.version,
    ).shipment
    assert sorting.sorted_at == harness.clock.now()
    harness.clock.advance(minutes=1)
    ready = harness.service.change_status(
        harness.operator,
        shipment.id,
        ShipmentStatus.READY_FOR_COURIER,
        expected_version=sorting.version,
    ).shipment
    assigned = harness.service.change_status(
        harness.operator,
        shipment.id,
        ShipmentStatus.ASSIGNED,
        expected_version=ready.version,
    ).shipment
    assert assigned.assigned_at is None
    harness.clock.advance(minutes=1)
    dispatched = harness.service.change_status(
        harness.operator,
        shipment.id,
        ShipmentStatus.DISPATCHED,
        expected_version=assigned.version,
    ).shipment
    assert dispatched.dispatched_at == harness.clock.now()


def test_report_and_resolve_problem_default_and_explicit_recovery(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
) -> None:
    shipment = harness.create()
    sorting = harness.service.change_status(
        harness.operator,
        shipment.id,
        ShipmentStatus.SORTING,
        expected_version=shipment.version,
    ).shipment
    problem = harness.service.report_problem(
        harness.operator,
        shipment.id,
        ProblemType.DAMAGED,
        expected_version=sorting.version,
        description="Corner crushed",
    )
    assert problem.previous_status is ShipmentStatus.SORTING
    in_problem = harness.service.get_shipment(harness.admin, shipment.id)
    assert in_problem.status is ShipmentStatus.PROBLEM
    with pytest.raises(ShipmentProblemOpenError):
        harness.service.report_problem(
            harness.operator,
            shipment.id,
            ProblemType.DAMAGED,
            expected_version=in_problem.version,
        )
    resolved = harness.service.resolve_problem(
        harness.supervisor,
        shipment.id,
        expected_version=in_problem.version,
        recovery_status=ShipmentStatus.READY_FOR_COURIER,
        reason="Repacked",
    )
    assert resolved.resolved_by == harness.supervisor.user_id
    recovered = harness.service.get_shipment(harness.admin, shipment.id)
    assert recovered.status is ShipmentStatus.READY_FOR_COURIER
    assert _count(session_factory, ShipmentProblemModel) == 1
    assert _audit_actions(session_factory)[-1] == AuditAction.SHIPMENT_PROBLEM_RESOLVED.value
    history = harness.service.get_status_history(harness.admin, shipment.id)
    assert [(item.old_status, item.new_status) for item in history] == [
        (ShipmentStatus.RECEIVED, ShipmentStatus.SORTING),
        (ShipmentStatus.SORTING, ShipmentStatus.PROBLEM),
        (ShipmentStatus.PROBLEM, ShipmentStatus.READY_FOR_COURIER),
    ]

    default_recovery = harness.create()
    harness.service.report_problem(
        harness.operator,
        default_recovery.id,
        ProblemType.DAMAGED,
        expected_version=default_recovery.version,
    )
    in_problem = harness.service.get_shipment(harness.admin, default_recovery.id)
    harness.service.resolve_problem(
        harness.supervisor,
        default_recovery.id,
        expected_version=in_problem.version,
    )
    assert (
        harness.service.get_shipment(harness.admin, default_recovery.id).status
        is ShipmentStatus.RECEIVED
    )


def test_problem_validation_invalid_recovery_and_missing_open_problem(
    harness: ShipmentHarness,
) -> None:
    shipment = harness.create()
    with pytest.raises(InvalidShipmentError, match="description"):
        harness.service.report_problem(
            harness.operator,
            shipment.id,
            ProblemType.OTHER,
            expected_version=shipment.version,
        )
    with pytest.raises(ShipmentProblemNotFoundError):
        harness.service.resolve_problem(
            harness.supervisor,
            shipment.id,
            expected_version=shipment.version,
        )
    reported = harness.service.report_problem(
        harness.operator,
        shipment.id,
        ProblemType.WRONG_ADDRESS,
        expected_version=shipment.version,
    )
    current = harness.service.get_shipment(harness.admin, shipment.id)
    assert reported.resolved_at is None
    with pytest.raises(InvalidShipmentTransitionError):
        harness.service.resolve_problem(
            harness.supervisor,
            shipment.id,
            expected_version=current.version,
            recovery_status=ShipmentStatus.DISPATCHED,
        )
    archived = harness.service.archive_shipment(
        harness.admin,
        shipment.id,
        expected_version=current.version,
    )
    with pytest.raises(ShipmentArchivedError):
        harness.service.resolve_problem(
            harness.supervisor,
            shipment.id,
            expected_version=archived.version,
        )


def test_archive_restore_listing_and_operational_guards(
    harness: ShipmentHarness,
) -> None:
    shipment = harness.create()
    archived = harness.service.archive_shipment(
        harness.admin, shipment.id, expected_version=shipment.version
    )
    assert archived.archived_at == harness.clock.now()
    assert harness.service.list_shipments(harness.admin).total == 0
    assert harness.service.list_shipments(harness.admin, include_archived=True).total == 1
    with pytest.raises(ShipmentArchivedError):
        harness.service.change_status(
            harness.operator,
            shipment.id,
            ShipmentStatus.SORTING,
            expected_version=archived.version,
        )
    with pytest.raises(ShipmentArchivedError):
        harness.service.report_problem(
            harness.operator,
            shipment.id,
            ProblemType.DAMAGED,
            expected_version=archived.version,
        )
    with pytest.raises(PermissionDeniedError):
        harness.service.restore_shipment(
            harness.supervisor, shipment.id, expected_version=archived.version
        )
    restored = harness.service.restore_shipment(
        harness.admin, shipment.id, expected_version=archived.version
    )
    assert restored.archived_at is None
    assert harness.service.get_status_history(harness.admin, shipment.id) == ()


def test_creation_audit_failure_rolls_back_everything(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_count = _count(session_factory, AuditEventModel)

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(
        "warehouse_control_center.infrastructure.database.repositories.audit."
        "SqlAlchemyAuditRepository.add",
        fail,
    )
    with pytest.raises(RuntimeError, match="forced audit"):
        harness.create()
    assert _count(session_factory, ShipmentModel) == 0
    assert _count(session_factory, AuditEventModel) == audit_count
    with session_factory() as database:
        assert database.scalar(select(ShipmentNumberSequenceModel.next_value)) == 1


def test_creation_commit_failure_rolls_back_flushed_shipment_and_audit(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_count = _count(session_factory, AuditEventModel)

    def fail_after_flush(unit_of_work: SqlAlchemyUnitOfWork) -> None:
        unit_of_work.session.flush()
        raise RuntimeError("forced database commit failure")

    monkeypatch.setattr(SqlAlchemyUnitOfWork, "commit", fail_after_flush)
    with pytest.raises(RuntimeError, match="database commit failure"):
        harness.create()
    assert _count(session_factory, ShipmentModel) == 0
    assert _count(session_factory, AuditEventModel) == audit_count
    with session_factory() as database:
        assert database.scalar(select(ShipmentNumberSequenceModel.next_value)) == 1


def test_status_history_failure_rolls_back_shipment_change(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shipment = harness.create()
    before_audits = _count(session_factory, AuditEventModel)

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced history failure")

    monkeypatch.setattr(SqlAlchemyShipmentRepository, "add_history", fail)
    with pytest.raises(RuntimeError, match="forced history"):
        harness.service.change_status(
            harness.operator,
            shipment.id,
            ShipmentStatus.SORTING,
            expected_version=shipment.version,
        )
    unchanged = harness.service.get_shipment(harness.admin, shipment.id)
    assert unchanged.status is ShipmentStatus.RECEIVED
    assert unchanged.version == shipment.version
    assert _count(session_factory, ShipmentStatusHistoryModel) == 0
    assert _count(session_factory, AuditEventModel) == before_audits


def test_update_audit_failure_rolls_back_metadata_change(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shipment = harness.create()
    before_audits = _count(session_factory, AuditEventModel)

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(
        "warehouse_control_center.infrastructure.database.repositories.audit."
        "SqlAlchemyAuditRepository.add",
        fail,
    )
    with pytest.raises(RuntimeError, match="forced audit"):
        harness.service.update_shipment(
            harness.supervisor,
            shipment.id,
            expected_version=shipment.version,
            recipient_name="Changed",
            recipient_address=shipment.recipient_address,
            recipient_city=shipment.recipient_city,
            recipient_phone=shipment.recipient_phone,
            sender_name=shipment.sender_name,
            notes="must roll back",
        )
    unchanged = harness.service.get_shipment(harness.admin, shipment.id)
    assert unchanged.recipient_name == shipment.recipient_name
    assert unchanged.notes == shipment.notes
    assert unchanged.version == shipment.version
    assert _count(session_factory, AuditEventModel) == before_audits


def test_status_audit_failure_rolls_back_shipment_and_history(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shipment = harness.create()
    before_audits = _count(session_factory, AuditEventModel)

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(
        "warehouse_control_center.infrastructure.database.repositories.audit."
        "SqlAlchemyAuditRepository.add",
        fail,
    )
    with pytest.raises(RuntimeError, match="forced audit"):
        harness.service.change_status(
            harness.operator,
            shipment.id,
            ShipmentStatus.SORTING,
            expected_version=shipment.version,
        )
    unchanged = harness.service.get_shipment(harness.admin, shipment.id)
    assert unchanged.status is ShipmentStatus.RECEIVED
    assert unchanged.version == shipment.version
    assert _count(session_factory, ShipmentStatusHistoryModel) == 0
    assert _count(session_factory, AuditEventModel) == before_audits


def test_problem_report_audit_failure_rolls_back_all_writes(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shipment = harness.create()
    before_audits = _count(session_factory, AuditEventModel)

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(
        "warehouse_control_center.infrastructure.database.repositories.audit."
        "SqlAlchemyAuditRepository.add",
        fail,
    )
    with pytest.raises(RuntimeError, match="forced audit"):
        harness.service.report_problem(
            harness.operator,
            shipment.id,
            ProblemType.DAMAGED,
            expected_version=shipment.version,
        )
    unchanged = harness.service.get_shipment(harness.admin, shipment.id)
    assert unchanged.status is ShipmentStatus.RECEIVED
    assert unchanged.version == shipment.version
    assert _count(session_factory, ShipmentProblemModel) == 0
    assert _count(session_factory, ShipmentStatusHistoryModel) == 0
    assert _count(session_factory, AuditEventModel) == before_audits


def test_problem_resolution_audit_failure_rolls_back_all_writes(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shipment = harness.create()
    harness.service.report_problem(
        harness.operator,
        shipment.id,
        ProblemType.DAMAGED,
        expected_version=shipment.version,
    )
    in_problem = harness.service.get_shipment(harness.admin, shipment.id)
    before_audits = _count(session_factory, AuditEventModel)
    before_history = _count(session_factory, ShipmentStatusHistoryModel)

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(
        "warehouse_control_center.infrastructure.database.repositories.audit."
        "SqlAlchemyAuditRepository.add",
        fail,
    )
    with pytest.raises(RuntimeError, match="forced audit"):
        harness.service.resolve_problem(
            harness.supervisor,
            shipment.id,
            expected_version=in_problem.version,
        )
    unchanged = harness.service.get_shipment(harness.admin, shipment.id)
    assert unchanged.status is ShipmentStatus.PROBLEM
    assert unchanged.version == in_problem.version
    with session_factory() as database:
        problem = database.scalar(
            select(ShipmentProblemModel).where(ShipmentProblemModel.shipment_id == shipment.id)
        )
        assert problem is not None
        assert problem.resolved_at is None
        assert problem.resolved_by is None
    assert _count(session_factory, ShipmentStatusHistoryModel) == before_history
    assert _count(session_factory, AuditEventModel) == before_audits


def test_archive_audit_failure_rolls_back_archive(
    harness: ShipmentHarness,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shipment = harness.create()

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(
        "warehouse_control_center.infrastructure.database.repositories.audit."
        "SqlAlchemyAuditRepository.add",
        fail,
    )
    with pytest.raises(RuntimeError, match="forced audit"):
        harness.service.archive_shipment(
            harness.admin, shipment.id, expected_version=shipment.version
        )
    unchanged = harness.service.get_shipment(harness.admin, shipment.id)
    assert unchanged.archived_at is None
    assert unchanged.version == shipment.version


def test_get_open_problem_returns_dto_and_clears_after_resolution(
    harness: ShipmentHarness,
) -> None:
    shipment = harness.create()
    assert harness.service.get_open_problem(harness.admin, shipment.id) is None
    reported = harness.service.report_problem(
        harness.operator,
        shipment.id,
        ProblemType.DAMAGED,
        expected_version=shipment.version,
        description="Damaged corner",
    )

    open_problem = harness.service.get_open_problem(harness.admin, shipment.id)
    assert open_problem == reported
    in_problem = harness.service.get_shipment(harness.admin, shipment.id)
    harness.service.resolve_problem(
        harness.supervisor,
        shipment.id,
        expected_version=in_problem.version,
    )
    assert harness.service.get_open_problem(harness.admin, shipment.id) is None
