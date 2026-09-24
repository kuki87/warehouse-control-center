"""Authorized shipment operations with atomic audit, history, and problem writes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast

from warehouse_control_center.application.dto import (
    SessionContext,
    ShipmentDTO,
    ShipmentPage,
    ShipmentProblemDTO,
    ShipmentStatusChangeResult,
    ShipmentStatusHistoryDTO,
    ShipmentWeightCheckDTO,
)
from warehouse_control_center.application.ports.clock import Clock
from warehouse_control_center.application.ports.repositories import (
    ShipmentListQuery,
    ShipmentSortField,
    SortDirection,
)
from warehouse_control_center.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from warehouse_control_center.application.services._actor import require_current_actor
from warehouse_control_center.application.services._audit import make_audit_event
from warehouse_control_center.application.services._time import utc_timestamp
from warehouse_control_center.domain.entities import (
    AuditEvent,
    Shipment,
    ShipmentProblem,
    ShipmentStatusHistory,
    ShipmentWeightCheck,
    User,
)
from warehouse_control_center.domain.enums import (
    AuditAction,
    Permission,
    ProblemType,
    ShipmentStatus,
)
from warehouse_control_center.domain.exceptions import (
    ClientNotFoundError,
    DuplicateShipmentNumberError,
    InvalidClientStateError,
    InvalidShipmentError,
    InvalidShipmentQueryError,
    InvalidShipmentTransitionError,
    ShipmentArchivedError,
    ShipmentConflictError,
    ShipmentNotFoundError,
    ShipmentNumberAllocationError,
    ShipmentProblemNotFoundError,
    ShipmentProblemOpenError,
)
from warehouse_control_center.domain.measurements import (
    WeightTolerancePolicy,
    validate_dimension_cm,
    validate_package_count,
    validate_weight_g,
)
from warehouse_control_center.domain.shipment_validation import (
    validate_optional_city,
    validate_problem,
    validate_search_text,
    validate_shipment_fields,
    validate_shipment_metadata,
    validate_status_reason,
    validate_weight_check_note,
)
from warehouse_control_center.domain.shipment_workflow import (
    can_transition,
    require_recovery,
    require_transition,
)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
_SORT_FIELDS = frozenset(
    {
        "shipment_number",
        "recipient_name",
        "recipient_city",
        "status",
        "received_at",
        "updated_at",
    }
)
_SORT_DIRECTIONS = frozenset({"asc", "desc"})


class ShipmentService:
    """Shipment use cases; creation intentionally starts history at the first transition."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        weight_policy: WeightTolerancePolicy | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._weight_policy = weight_policy or WeightTolerancePolicy()

    def create_shipment(
        self,
        session: SessionContext,
        *,
        recipient_name: str,
        recipient_address: str,
        recipient_city: str,
        recipient_phone: str,
        sender_name: str | None,
        sender_client_id: int | None = None,
        package_count: int = 1,
        length_cm: Decimal | str | int | None = None,
        width_cm: Decimal | str | int | None = None,
        height_cm: Decimal | str | int | None = None,
        declared_weight_g: int | None = None,
        notes: str | None = None,
    ) -> ShipmentDTO:
        validated_package_count = validate_package_count(package_count)
        validated_length = validate_dimension_cm("Length", length_cm)
        validated_width = validate_dimension_cm("Width", width_cm)
        validated_height = validate_dimension_cm("Height", height_cm)
        validated_weight = validate_weight_g("Declared weight", declared_weight_g, required=False)
        if sender_client_id is not None and (
            isinstance(sender_client_id, bool)
            or not isinstance(sender_client_id, int)
            or sender_client_id < 1
        ):
            raise InvalidShipmentError("Sender client id must be a positive integer")
        with self._uow_factory() as uow:
            actor = require_current_actor(uow, session, Permission.CREATE_SHIPMENT)
            resolved_sender = sender_name
            if sender_client_id is not None:
                client = uow.clients.get_by_id(sender_client_id)
                if client is None:
                    raise ClientNotFoundError(f"Client {sender_client_id} does not exist")
                if not client.active:
                    raise InvalidClientStateError(
                        "Inactive clients cannot be used for new shipments"
                    )
                resolved_sender = client.company_name
            fields = validate_shipment_metadata(
                recipient_name=recipient_name,
                recipient_address=recipient_address,
                recipient_city=recipient_city,
                recipient_phone=recipient_phone,
                sender_name=resolved_sender,
                notes=notes,
            )
            shipment_number = uow.shipment_numbers.allocate()
            now = utc_timestamp(self._clock.now())
            try:
                shipment = uow.shipments.add(
                    Shipment(
                        shipment_number=shipment_number,
                        recipient_name=fields.recipient_name,
                        recipient_address=fields.recipient_address,
                        recipient_city=fields.recipient_city,
                        recipient_phone=fields.recipient_phone,
                        sender_name=fields.sender_name,
                        sender_client_id=sender_client_id,
                        package_count=validated_package_count,
                        length_cm=validated_length,
                        width_cm=validated_width,
                        height_cm=validated_height,
                        declared_weight_g=validated_weight,
                        notes=fields.notes,
                        created_by=_persisted_id(actor),
                        status=ShipmentStatus.RECEIVED,
                        received_at=now,
                        created_at=now,
                        updated_at=now,
                        version=1,
                    )
                )
            except DuplicateShipmentNumberError as error:
                raise ShipmentNumberAllocationError(
                    "Shipment number conflicts with an existing identifier"
                ) from error
            uow.audits.add(
                _shipment_audit(
                    AuditAction.SHIPMENT_CREATED,
                    actor,
                    shipment,
                    now,
                    details={"shipment_number": shipment.shipment_number},
                )
            )
            uow.commit()
        return ShipmentDTO.from_entity(shipment)

    def record_control_weight(
        self,
        session: SessionContext,
        shipment_id: int,
        *,
        measured_weight_g: int,
        note: str | None = None,
    ) -> ShipmentWeightCheckDTO:
        measured = validate_weight_g("Measured weight", measured_weight_g, required=True)
        assert measured is not None
        canonical_note = validate_weight_check_note(note)
        with self._uow_factory() as uow:
            actor = require_current_actor(uow, session, Permission.CONTROL_WEIGHT_SHIPMENT)
            shipment = _get_shipment(uow, shipment_id)
            _require_operational(shipment)
            if shipment.declared_weight_g is None:
                raise InvalidShipmentError("A declared weight is required before control weighing")
            difference, result = self._weight_policy.evaluate(shipment.declared_weight_g, measured)
            now = utc_timestamp(self._clock.now())
            check = uow.shipments.add_weight_check(
                ShipmentWeightCheck(
                    shipment_id=shipment_id,
                    declared_weight_g_snapshot=shipment.declared_weight_g,
                    measured_weight_g=measured,
                    absolute_difference_g=difference,
                    tolerance_abs_g_snapshot=self._weight_policy.absolute_tolerance_g,
                    result=result,
                    checked_by_user_id=_persisted_id(actor),
                    checked_at=now,
                    note=canonical_note,
                )
            )
            uow.audits.add(
                _shipment_audit(
                    AuditAction.SHIPMENT_WEIGHT_CHECKED,
                    actor,
                    shipment,
                    now,
                    details={
                        "shipment_number": shipment.shipment_number,
                        "measured_weight_g": measured,
                        "result": result.value,
                    },
                )
            )
            uow.commit()
        return ShipmentWeightCheckDTO.from_entity(check)

    def get_weight_checks(
        self, session: SessionContext, shipment_id: int
    ) -> tuple[ShipmentWeightCheckDTO, ...]:
        with self._uow_factory() as uow:
            require_current_actor(uow, session, Permission.VIEW_SHIPMENTS)
            _get_shipment(uow, shipment_id)
            return tuple(
                ShipmentWeightCheckDTO.from_entity(item)
                for item in uow.shipments.list_weight_checks(shipment_id)
            )

    def update_shipment(
        self,
        session: SessionContext,
        shipment_id: int,
        *,
        expected_version: int,
        recipient_name: str,
        recipient_address: str,
        recipient_city: str,
        recipient_phone: str,
        sender_name: str,
        notes: str | None,
    ) -> ShipmentDTO:
        _require_version(expected_version)
        with self._uow_factory() as uow:
            actor = require_current_actor(uow, session, Permission.EDIT_SHIPMENT)
            shipment = _get_shipment(uow, shipment_id)
            _require_operational(shipment)
            _require_expected_version(shipment, expected_version)
            fields = validate_shipment_fields(
                shipment_number=shipment.shipment_number,
                recipient_name=recipient_name,
                recipient_address=recipient_address,
                recipient_city=recipient_city,
                recipient_phone=recipient_phone,
                sender_name=sender_name,
                notes=notes,
            )
            shipment.recipient_name = fields.recipient_name
            shipment.recipient_address = fields.recipient_address
            shipment.recipient_city = fields.recipient_city
            shipment.recipient_phone = fields.recipient_phone
            shipment.sender_name = fields.sender_name
            shipment.notes = fields.notes
            now = utc_timestamp(self._clock.now())
            shipment.updated_at = now
            saved = uow.shipments.save(shipment)
            uow.audits.add(
                _shipment_audit(
                    AuditAction.SHIPMENT_UPDATED,
                    actor,
                    saved,
                    now,
                    details={
                        "shipment_number": saved.shipment_number,
                        "fields": [
                            "recipient_name",
                            "recipient_address",
                            "recipient_city",
                            "recipient_phone",
                            "sender_name",
                            "notes",
                        ],
                    },
                )
            )
            uow.commit()
        return ShipmentDTO.from_entity(saved)

    def get_shipment(self, session: SessionContext, shipment_id: int) -> ShipmentDTO:
        with self._uow_factory() as uow:
            require_current_actor(uow, session, Permission.VIEW_SHIPMENTS)
            return ShipmentDTO.from_entity(_get_shipment(uow, shipment_id))

    def get_by_shipment_number(self, session: SessionContext, shipment_number: str) -> ShipmentDTO:
        if not shipment_number or not shipment_number.strip():
            raise InvalidShipmentError("Shipment number is required")
        with self._uow_factory() as uow:
            require_current_actor(uow, session, Permission.VIEW_SHIPMENTS)
            shipment = uow.shipments.get_by_normalized_shipment_number(shipment_number)
            if shipment is None:
                raise ShipmentNotFoundError("Shipment does not exist")
            return ShipmentDTO.from_entity(shipment)

    def list_shipments(
        self,
        session: SessionContext,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        search: str | None = None,
        status: ShipmentStatus | None = None,
        courier_id: int | None = None,
        city: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        include_archived: bool = False,
        problem_only: bool = False,
        sort_by: str = "received_at",
        sort_direction: str = "desc",
    ) -> ShipmentPage:
        _validate_pagination(page, page_size)
        canonical_search = validate_search_text(search)
        canonical_city = validate_optional_city(city)
        if status is not None and not isinstance(status, ShipmentStatus):
            raise InvalidShipmentQueryError("Unsupported shipment status filter")
        if courier_id is not None and (
            isinstance(courier_id, bool) or not isinstance(courier_id, int) or courier_id < 1
        ):
            raise InvalidShipmentQueryError("Courier id must be a positive integer")
        start = _optional_utc(date_from)
        end = _optional_utc(date_to)
        if start is not None and end is not None and start > end:
            raise InvalidShipmentQueryError("Date from must not be after date to")
        if sort_by not in _SORT_FIELDS:
            raise InvalidShipmentQueryError("Unsupported shipment sort field")
        if sort_direction not in _SORT_DIRECTIONS:
            raise InvalidShipmentQueryError("Sort direction must be 'asc' or 'desc'")
        query = ShipmentListQuery(
            offset=(page - 1) * page_size,
            limit=page_size,
            search=canonical_search,
            status=status,
            courier_id=courier_id,
            city=canonical_city,
            date_from=start,
            date_to=end,
            include_archived=include_archived,
            problem_only=problem_only,
            sort_by=cast(ShipmentSortField, sort_by),
            sort_direction=cast(SortDirection, sort_direction),
        )
        with self._uow_factory() as uow:
            require_current_actor(uow, session, Permission.VIEW_SHIPMENTS)
            shipments, total = uow.shipments.list_page(query)
        return ShipmentPage(
            tuple(ShipmentDTO.from_entity(shipment) for shipment in shipments),
            page,
            page_size,
            total,
        )

    def get_status_history(
        self, session: SessionContext, shipment_id: int
    ) -> tuple[ShipmentStatusHistoryDTO, ...]:
        with self._uow_factory() as uow:
            require_current_actor(uow, session, Permission.VIEW_SHIPMENTS)
            _get_shipment(uow, shipment_id)
            return tuple(
                ShipmentStatusHistoryDTO.from_entity(item)
                for item in uow.shipments.list_history(shipment_id)
            )

    def get_open_problem(
        self, session: SessionContext, shipment_id: int
    ) -> ShipmentProblemDTO | None:
        """Return the unresolved problem without exposing repository entities to the UI."""
        with self._uow_factory() as uow:
            require_current_actor(uow, session, Permission.VIEW_SHIPMENTS)
            _get_shipment(uow, shipment_id)
            problem = uow.shipments.get_open_problem(shipment_id)
            return ShipmentProblemDTO.from_entity(problem) if problem is not None else None

    def change_status(
        self,
        session: SessionContext,
        shipment_id: int,
        target_status: ShipmentStatus,
        *,
        expected_version: int,
        reason: str | None = None,
        override: bool = False,
    ) -> ShipmentStatusChangeResult:
        _require_version(expected_version)
        if not isinstance(target_status, ShipmentStatus):
            raise InvalidShipmentError("Unsupported shipment status")
        with self._uow_factory() as uow:
            actor = require_current_actor(uow, session, Permission.CHANGE_SHIPMENT_STATUS)
            shipment = _get_shipment(uow, shipment_id)
            _require_operational(shipment)
            if shipment.status is target_status:
                return ShipmentStatusChangeResult(ShipmentDTO.from_entity(shipment), changed=False)
            if target_status is ShipmentStatus.PROBLEM:
                raise InvalidShipmentTransitionError(
                    "Use report_problem to move a shipment into PROBLEM"
                )
            _require_expected_version(shipment, expected_version)
            if shipment.status is ShipmentStatus.PROBLEM:
                raise InvalidShipmentTransitionError(
                    "Resolve the open problem before changing shipment status"
                )
            valid = can_transition(shipment.status, target_status)
            is_override = not valid and override
            canonical_reason = validate_status_reason(reason, required=is_override)
            if not valid and not override:
                require_transition(shipment.status, target_status)
            if is_override:
                require_current_actor(uow, session, Permission.OVERRIDE_STATUS_TRANSITION)
            now = utc_timestamp(self._clock.now())
            old_status = shipment.status
            _apply_status(shipment, target_status, now)
            saved = uow.shipments.save(shipment)
            uow.shipments.add_history(
                ShipmentStatusHistory(
                    shipment_id=saved.id or shipment_id,
                    old_status=old_status,
                    new_status=target_status,
                    changed_by=_persisted_id(actor),
                    timestamp=now,
                    reason=canonical_reason,
                    is_admin_override=is_override,
                )
            )
            action = (
                AuditAction.SHIPMENT_STATUS_OVERRIDDEN
                if is_override
                else AuditAction.SHIPMENT_STATUS_CHANGED
            )
            uow.audits.add(
                _shipment_audit(
                    action,
                    actor,
                    saved,
                    now,
                    details={
                        "shipment_number": saved.shipment_number,
                        "old_status": old_status.value,
                        "new_status": target_status.value,
                        "reason": canonical_reason,
                        "is_admin_override": is_override,
                    },
                )
            )
            uow.commit()
        return ShipmentStatusChangeResult(ShipmentDTO.from_entity(saved), changed=True)

    def archive_shipment(
        self,
        session: SessionContext,
        shipment_id: int,
        *,
        expected_version: int,
    ) -> ShipmentDTO:
        return self._set_archived(session, shipment_id, expected_version, archive=True)

    def restore_shipment(
        self,
        session: SessionContext,
        shipment_id: int,
        *,
        expected_version: int,
    ) -> ShipmentDTO:
        return self._set_archived(session, shipment_id, expected_version, archive=False)

    def _set_archived(
        self,
        session: SessionContext,
        shipment_id: int,
        expected_version: int,
        *,
        archive: bool,
    ) -> ShipmentDTO:
        _require_version(expected_version)
        permission = Permission.ARCHIVE_SHIPMENT if archive else Permission.RESTORE_SHIPMENT
        with self._uow_factory() as uow:
            actor = require_current_actor(uow, session, permission)
            shipment = _get_shipment(uow, shipment_id)
            _require_expected_version(shipment, expected_version)
            if archive and shipment.archived_at is not None:
                raise ShipmentArchivedError("Shipment is already archived")
            if not archive and shipment.archived_at is None:
                raise InvalidShipmentError("Shipment is not archived")
            now = utc_timestamp(self._clock.now())
            shipment.archived_at = now if archive else None
            shipment.updated_at = now
            saved = uow.shipments.save(shipment)
            action = AuditAction.SHIPMENT_ARCHIVED if archive else AuditAction.SHIPMENT_RESTORED
            uow.audits.add(
                _shipment_audit(
                    action,
                    actor,
                    saved,
                    now,
                    details={"shipment_number": saved.shipment_number},
                )
            )
            uow.commit()
        return ShipmentDTO.from_entity(saved)

    def report_problem(
        self,
        session: SessionContext,
        shipment_id: int,
        problem_type: ProblemType,
        *,
        expected_version: int,
        description: str | None = None,
    ) -> ShipmentProblemDTO:
        _require_version(expected_version)
        validated_type, validated_description = validate_problem(problem_type, description)
        with self._uow_factory() as uow:
            actor = require_current_actor(uow, session, Permission.MARK_PROBLEM)
            shipment = _get_shipment(uow, shipment_id)
            _require_operational(shipment)
            _require_expected_version(shipment, expected_version)
            if uow.shipments.get_open_problem(shipment_id) is not None:
                raise ShipmentProblemOpenError("Shipment already has an unresolved problem")
            require_transition(shipment.status, ShipmentStatus.PROBLEM)
            now = utc_timestamp(self._clock.now())
            previous_status = shipment.status
            _apply_status(shipment, ShipmentStatus.PROBLEM, now)
            saved = uow.shipments.save(shipment)
            problem = uow.shipments.add_problem(
                ShipmentProblem(
                    shipment_id=saved.id or shipment_id,
                    problem_type=validated_type,
                    description=validated_description,
                    previous_status=previous_status,
                    reported_by=_persisted_id(actor),
                    reported_at=now,
                )
            )
            uow.shipments.add_history(
                ShipmentStatusHistory(
                    shipment_id=saved.id or shipment_id,
                    old_status=previous_status,
                    new_status=ShipmentStatus.PROBLEM,
                    changed_by=_persisted_id(actor),
                    timestamp=now,
                    reason=validated_description,
                )
            )
            uow.audits.add(
                _shipment_audit(
                    AuditAction.SHIPMENT_PROBLEM_REPORTED,
                    actor,
                    saved,
                    now,
                    details={
                        "shipment_number": saved.shipment_number,
                        "old_status": previous_status.value,
                        "problem_type": validated_type.value,
                    },
                )
            )
            uow.commit()
        return ShipmentProblemDTO.from_entity(problem)

    def resolve_problem(
        self,
        session: SessionContext,
        shipment_id: int,
        *,
        expected_version: int,
        recovery_status: ShipmentStatus | None = None,
        reason: str | None = None,
    ) -> ShipmentProblemDTO:
        _require_version(expected_version)
        canonical_reason = validate_status_reason(reason, required=False)
        if recovery_status is not None and not isinstance(recovery_status, ShipmentStatus):
            raise InvalidShipmentError("Unsupported recovery status")
        with self._uow_factory() as uow:
            actor = require_current_actor(uow, session, Permission.RESOLVE_PROBLEM)
            shipment = _get_shipment(uow, shipment_id)
            _require_operational(shipment)
            _require_expected_version(shipment, expected_version)
            if shipment.status is not ShipmentStatus.PROBLEM:
                raise ShipmentProblemNotFoundError("Shipment has no unresolved problem")
            problem = uow.shipments.get_open_problem(shipment_id)
            if problem is None:
                raise ShipmentProblemNotFoundError("Shipment has no unresolved problem")
            target = recovery_status or problem.previous_status
            require_recovery(problem.previous_status, target)
            now = utc_timestamp(self._clock.now())
            problem.resolved_by = _persisted_id(actor)
            problem.resolved_at = now
            resolved = uow.shipments.save_problem(problem)
            _apply_status(shipment, target, now)
            saved = uow.shipments.save(shipment)
            uow.shipments.add_history(
                ShipmentStatusHistory(
                    shipment_id=saved.id or shipment_id,
                    old_status=ShipmentStatus.PROBLEM,
                    new_status=target,
                    changed_by=_persisted_id(actor),
                    timestamp=now,
                    reason=canonical_reason,
                )
            )
            uow.audits.add(
                _shipment_audit(
                    AuditAction.SHIPMENT_PROBLEM_RESOLVED,
                    actor,
                    saved,
                    now,
                    details={
                        "shipment_number": saved.shipment_number,
                        "new_status": target.value,
                        "problem_type": problem.problem_type.value,
                    },
                )
            )
            uow.commit()
        return ShipmentProblemDTO.from_entity(resolved)


def _get_shipment(uow: UnitOfWork, shipment_id: int) -> Shipment:
    shipment = uow.shipments.get_by_id(shipment_id)
    if shipment is None:
        raise ShipmentNotFoundError(f"Shipment {shipment_id} does not exist")
    return shipment


def _require_operational(shipment: Shipment) -> None:
    if shipment.archived_at is not None:
        raise ShipmentArchivedError("Archived shipments cannot be changed")


def _require_version(version: int) -> None:
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise InvalidShipmentError("Expected version must be a positive integer")


def _require_expected_version(shipment: Shipment, expected: int) -> None:
    if shipment.version != expected:
        raise ShipmentConflictError("Shipment was changed by another operation")


def _persisted_id(user: User) -> int:
    if user.id is None:
        raise RuntimeError("Persisted actor is missing an id")
    return user.id


def _apply_status(shipment: Shipment, target: ShipmentStatus, now: datetime) -> None:
    shipment.status = target
    shipment.updated_at = now
    if target is ShipmentStatus.SORTING and shipment.sorted_at is None:
        shipment.sorted_at = now
    if target is ShipmentStatus.DISPATCHED and shipment.dispatched_at is None:
        shipment.dispatched_at = now


def _shipment_audit(
    action: AuditAction,
    actor: User,
    shipment: Shipment,
    timestamp: datetime,
    *,
    details: dict[str, object],
) -> AuditEvent:
    return make_audit_event(
        action=action,
        actor_id=_persisted_id(actor),
        actor_name=actor.username,
        entity_id=shipment.id or shipment.shipment_number_normalized,
        entity_type="SHIPMENT",
        timestamp=timestamp,
        details=details,
    )


def _validate_pagination(page: int, page_size: int) -> None:
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise InvalidShipmentQueryError("Page must be a positive integer")
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= MAX_PAGE_SIZE
    ):
        raise InvalidShipmentQueryError(f"Page size must be between 1 and {MAX_PAGE_SIZE}")


def _optional_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    try:
        return utc_timestamp(value)
    except ValueError as error:
        raise InvalidShipmentQueryError("Date filters must be timezone-aware") from error
