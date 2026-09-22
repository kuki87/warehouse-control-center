"""Authorized shipment operations with atomic audit, history, and problem writes."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from warehouse_control_center.application.dto import (
    SessionContext,
    ShipmentDTO,
    ShipmentPage,
    ShipmentProblemDTO,
    ShipmentStatusChangeResult,
    ShipmentStatusHistoryDTO,
)
from warehouse_control_center.application.permissions import has_permission, require_permission
from warehouse_control_center.application.ports.clock import Clock
from warehouse_control_center.application.ports.repositories import (
    ShipmentListQuery,
    ShipmentSortField,
    SortDirection,
)
from warehouse_control_center.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from warehouse_control_center.application.services._audit import make_audit_event
from warehouse_control_center.application.services._time import utc_timestamp
from warehouse_control_center.domain.entities import (
    AuditEvent,
    Shipment,
    ShipmentProblem,
    ShipmentStatusHistory,
    User,
)
from warehouse_control_center.domain.enums import (
    AuditAction,
    Permission,
    ProblemType,
    ShipmentStatus,
)
from warehouse_control_center.domain.exceptions import (
    InvalidPasswordError,
    InvalidShipmentError,
    InvalidShipmentQueryError,
    InvalidShipmentTransitionError,
    InvalidUserRoleError,
    PermissionDeniedError,
    ShipmentArchivedError,
    ShipmentConflictError,
    ShipmentNotFoundError,
    ShipmentProblemNotFoundError,
    ShipmentProblemOpenError,
)
from warehouse_control_center.domain.shipment_validation import (
    validate_optional_city,
    validate_problem,
    validate_search_text,
    validate_shipment_fields,
    validate_status_reason,
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
        "tracking_number",
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

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    def create_shipment(
        self,
        session: SessionContext,
        *,
        tracking_number: str,
        barcode: str,
        recipient_name: str,
        recipient_address: str,
        recipient_city: str,
        recipient_phone: str,
        sender_name: str,
        notes: str | None = None,
    ) -> ShipmentDTO:
        fields = validate_shipment_fields(
            tracking_number=tracking_number,
            barcode=barcode,
            recipient_name=recipient_name,
            recipient_address=recipient_address,
            recipient_city=recipient_city,
            recipient_phone=recipient_phone,
            sender_name=sender_name,
            notes=notes,
        )
        with self._uow_factory() as uow:
            actor = _require_current_actor(uow, session, Permission.CREATE_SHIPMENT)
            now = utc_timestamp(self._clock.now())
            shipment = uow.shipments.add(
                Shipment(
                    tracking_number=fields.tracking_number,
                    barcode=fields.barcode,
                    recipient_name=fields.recipient_name,
                    recipient_address=fields.recipient_address,
                    recipient_city=fields.recipient_city,
                    recipient_phone=fields.recipient_phone,
                    sender_name=fields.sender_name,
                    notes=fields.notes,
                    created_by=_persisted_id(actor),
                    status=ShipmentStatus.RECEIVED,
                    received_at=now,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            )
            uow.audits.add(
                _shipment_audit(
                    AuditAction.SHIPMENT_CREATED,
                    actor,
                    shipment,
                    now,
                    details={"tracking_number": shipment.tracking_number},
                )
            )
            uow.commit()
        return ShipmentDTO.from_entity(shipment)

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
            actor = _require_current_actor(uow, session, Permission.EDIT_SHIPMENT)
            shipment = _get_shipment(uow, shipment_id)
            _require_operational(shipment)
            _require_expected_version(shipment, expected_version)
            fields = validate_shipment_fields(
                tracking_number=shipment.tracking_number,
                barcode=shipment.barcode,
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
                        "tracking_number": saved.tracking_number,
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
            _require_current_actor(uow, session, Permission.VIEW_SHIPMENTS)
            return ShipmentDTO.from_entity(_get_shipment(uow, shipment_id))

    def get_by_tracking_number(self, session: SessionContext, tracking_number: str) -> ShipmentDTO:
        if not tracking_number or not tracking_number.strip():
            raise InvalidShipmentError("Tracking number is required")
        with self._uow_factory() as uow:
            _require_current_actor(uow, session, Permission.VIEW_SHIPMENTS)
            shipment = uow.shipments.get_by_normalized_tracking_number(tracking_number)
            if shipment is None:
                raise ShipmentNotFoundError("Shipment does not exist")
            return ShipmentDTO.from_entity(shipment)

    def get_by_barcode(self, session: SessionContext, barcode: str) -> ShipmentDTO:
        if not barcode or not barcode.strip():
            raise InvalidShipmentError("Barcode is required")
        with self._uow_factory() as uow:
            _require_current_actor(uow, session, Permission.VIEW_SHIPMENTS)
            shipment = uow.shipments.get_by_normalized_barcode(barcode)
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
            _require_current_actor(uow, session, Permission.VIEW_SHIPMENTS)
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
            _require_current_actor(uow, session, Permission.VIEW_SHIPMENTS)
            _get_shipment(uow, shipment_id)
            return tuple(
                ShipmentStatusHistoryDTO.from_entity(item)
                for item in uow.shipments.list_history(shipment_id)
            )

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
            actor = _require_current_actor(uow, session, Permission.CHANGE_SHIPMENT_STATUS)
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
                _require_actor_permission(actor, session, Permission.OVERRIDE_STATUS_TRANSITION)
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
                        "tracking_number": saved.tracking_number,
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
            actor = _require_current_actor(uow, session, permission)
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
                    details={"tracking_number": saved.tracking_number},
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
            actor = _require_current_actor(uow, session, Permission.MARK_PROBLEM)
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
                        "tracking_number": saved.tracking_number,
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
            actor = _require_current_actor(uow, session, Permission.RESOLVE_PROBLEM)
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
                        "tracking_number": saved.tracking_number,
                        "new_status": target.value,
                        "problem_type": problem.problem_type.value,
                    },
                )
            )
            uow.commit()
        return ShipmentProblemDTO.from_entity(resolved)


def _require_current_actor(
    uow: UnitOfWork,
    session: SessionContext,
    permission: Permission,
) -> User:
    require_permission(session, permission)
    try:
        actor = uow.users.get_by_id(session.user_id)
    except (InvalidPasswordError, InvalidUserRoleError):
        raise PermissionDeniedError("Current session is no longer authorized") from None
    if (
        actor is None
        or actor.id is None
        or not actor.active
        or actor.archived_at is not None
        or actor.credential_version != session.credential_version
        or actor.username != session.username
    ):
        raise PermissionDeniedError("Current session is no longer authorized")
    _require_actor_permission(actor, session, permission)
    return actor


def _require_actor_permission(
    actor: User,
    session: SessionContext,
    permission: Permission,
) -> None:
    current = SessionContext(
        user_id=_persisted_id(actor),
        username=actor.username,
        role=actor.role,
        authenticated_at=session.authenticated_at,
        must_change_password=actor.must_change_password,
        credential_version=actor.credential_version,
    )
    if not has_permission(current, permission):
        raise PermissionDeniedError("Current session is no longer authorized")


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
        entity_id=shipment.id or shipment.tracking_number_normalized,
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
