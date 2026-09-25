"""Shipment persistence, optimistic writes, history, problems, and database paging."""

from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.sql.elements import ColumnElement

from warehouse_control_center.application.ports.repositories import ShipmentListQuery
from warehouse_control_center.domain.entities import (
    Shipment,
    ShipmentProblem,
    ShipmentStatusHistory,
    ShipmentWeightCheck,
)
from warehouse_control_center.domain.exceptions import (
    DatabaseBusyError,
    DuplicateShipmentNumberError,
    InvalidShipmentQueryError,
    ShipmentConflictError,
    ShipmentProblemOpenError,
)
from warehouse_control_center.domain.measurements import dimension_cm_to_mm
from warehouse_control_center.domain.normalization import normalize_shipment_number
from warehouse_control_center.infrastructure.database.models import (
    ShipmentModel,
    ShipmentProblemModel,
    ShipmentServiceModel,
    ShipmentStatusHistoryModel,
    ShipmentWeightCheckModel,
)
from warehouse_control_center.infrastructure.database.repositories.mapping import (
    history_to_entity,
    history_to_model,
    problem_to_entity,
    problem_to_model,
    shipment_to_entity,
    shipment_to_model,
    weight_check_to_entity,
    weight_check_to_model,
)

_SORT_COLUMNS = {
    "shipment_number": ShipmentModel.shipment_number_normalized,
    "recipient_name": ShipmentModel.recipient_name,
    "recipient_city": ShipmentModel.recipient_city,
    "status": ShipmentModel.status,
    "received_at": ShipmentModel.received_at,
    "updated_at": ShipmentModel.updated_at,
}


class SqlAlchemyShipmentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, shipment: Shipment) -> Shipment:
        model = shipment_to_model(shipment)
        self._session.add(model)
        self._flush_identifiers()
        return shipment_to_entity(model)

    def save(self, shipment: Shipment) -> Shipment:
        if shipment.id is None:
            raise ValueError("Cannot save a shipment without an id")
        model = self._session.get(ShipmentModel, shipment.id)
        if model is None:
            raise ValueError(f"Shipment {shipment.id} does not exist")
        if model.version != shipment.version:
            raise ShipmentConflictError("Shipment was changed by another operation")
        model.recipient_name = shipment.recipient_name
        model.recipient_address = shipment.recipient_address
        model.recipient_city = shipment.recipient_city
        model.recipient_phone = shipment.recipient_phone
        model.sender_name = shipment.sender_name
        model.sender_client_id = shipment.sender_client_id
        model.package_count = shipment.package_count
        model.length_mm = dimension_cm_to_mm(shipment.length_cm)
        model.width_mm = dimension_cm_to_mm(shipment.width_cm)
        model.height_mm = dimension_cm_to_mm(shipment.height_cm)
        model.declared_weight_g = shipment.declared_weight_g
        model.declared_value_fen = shipment.declared_value_fen
        model.cod_enabled = shipment.cod_enabled
        model.cod_amount_fen = shipment.cod_amount_fen
        model.payer = shipment.payer
        model.payment_method = shipment.payment_method
        existing_services = {row.service_type: row for row in model.service_rows}
        model.service_rows[:] = [
            existing_services.get(service)
            or ShipmentServiceModel(service_type=service, created_at=shipment.updated_at)
            for service in sorted(shipment.services, key=lambda item: item.value)
        ]
        model.status = shipment.status
        model.received_at = shipment.received_at
        model.sorted_at = shipment.sorted_at
        model.assigned_at = shipment.assigned_at
        model.dispatched_at = shipment.dispatched_at
        model.notes = shipment.notes
        model.archived_at = shipment.archived_at
        model.updated_at = shipment.updated_at
        try:
            self._session.flush()
        except StaleDataError:
            raise ShipmentConflictError("Shipment was changed by another operation") from None
        except OperationalError as error:
            _raise_if_busy(error)
            raise
        return shipment_to_entity(model)

    def get_by_id(self, shipment_id: int) -> Shipment | None:
        model = self._session.get(ShipmentModel, shipment_id)
        return shipment_to_entity(model) if model is not None else None

    def get_by_normalized_shipment_number(self, shipment_number: str) -> Shipment | None:
        statement = select(ShipmentModel).where(
            ShipmentModel.shipment_number_normalized == normalize_shipment_number(shipment_number)
        )
        model = self._session.scalar(statement)
        return shipment_to_entity(model) if model is not None else None

    def list_page(self, query: ShipmentListQuery) -> tuple[list[Shipment], int]:
        if query.sort_by not in _SORT_COLUMNS:
            raise InvalidShipmentQueryError("Unsupported shipment sort field")
        filters: list[ColumnElement[bool]] = []
        if not query.include_archived:
            filters.append(ShipmentModel.archived_at.is_(None))
        if query.status is not None:
            filters.append(ShipmentModel.status == query.status)
        if query.courier_id is not None:
            filters.append(ShipmentModel.courier_id == query.courier_id)
        if query.city is not None:
            filters.append(ShipmentModel.recipient_city.collate("NOCASE") == query.city)
        if query.date_from is not None:
            filters.append(ShipmentModel.received_at >= query.date_from)
        if query.date_to is not None:
            filters.append(ShipmentModel.received_at <= query.date_to)
        if query.problem_only:
            filters.append(
                exists().where(
                    ShipmentProblemModel.shipment_id == ShipmentModel.id,
                    ShipmentProblemModel.resolved_at.is_(None),
                )
            )
        if query.search:
            term = query.search.strip()
            normalized_shipment_number = normalize_shipment_number(term)
            pattern = f"%{_escape_like(term)}%"
            filters.append(
                or_(
                    ShipmentModel.shipment_number_normalized.contains(
                        normalized_shipment_number, autoescape=True
                    ),
                    ShipmentModel.recipient_name.ilike(pattern, escape="\\"),
                    ShipmentModel.recipient_phone.ilike(pattern, escape="\\"),
                    ShipmentModel.recipient_address.ilike(pattern, escape="\\"),
                )
            )
        count_statement = select(func.count()).select_from(ShipmentModel).where(*filters)
        total = self._session.scalar(count_statement) or 0
        sort_column = _SORT_COLUMNS[query.sort_by]
        order = sort_column.asc() if query.sort_direction == "asc" else sort_column.desc()
        statement = (
            select(ShipmentModel)
            .where(*filters)
            .order_by(order, ShipmentModel.id.asc())
            .offset(query.offset)
            .limit(query.limit)
        )
        return [shipment_to_entity(model) for model in self._session.scalars(statement)], total

    def add_history(self, history: ShipmentStatusHistory) -> ShipmentStatusHistory:
        model = history_to_model(history)
        self._session.add(model)
        self._flush()
        return history_to_entity(model)

    def list_history(self, shipment_id: int) -> list[ShipmentStatusHistory]:
        statement = (
            select(ShipmentStatusHistoryModel)
            .where(ShipmentStatusHistoryModel.shipment_id == shipment_id)
            .order_by(ShipmentStatusHistoryModel.timestamp, ShipmentStatusHistoryModel.id)
        )
        return [history_to_entity(model) for model in self._session.scalars(statement)]

    def add_problem(self, problem: ShipmentProblem) -> ShipmentProblem:
        model = problem_to_model(problem)
        self._session.add(model)
        try:
            self._flush()
        except IntegrityError as error:
            if "shipment_problems.shipment_id" in str(error):
                raise ShipmentProblemOpenError(
                    "Shipment already has an unresolved problem"
                ) from None
            raise
        return problem_to_entity(model)

    def save_problem(self, problem: ShipmentProblem) -> ShipmentProblem:
        if problem.id is None:
            raise ValueError("Cannot save a shipment problem without an id")
        model = self._session.get(ShipmentProblemModel, problem.id)
        if model is None:
            raise ValueError(f"Shipment problem {problem.id} does not exist")
        model.resolved_by = problem.resolved_by
        model.resolved_at = problem.resolved_at
        self._flush()
        return problem_to_entity(model)

    def get_open_problem(self, shipment_id: int) -> ShipmentProblem | None:
        statement = select(ShipmentProblemModel).where(
            ShipmentProblemModel.shipment_id == shipment_id,
            ShipmentProblemModel.resolved_at.is_(None),
        )
        model = self._session.scalar(statement)
        return problem_to_entity(model) if model is not None else None

    def add_weight_check(self, check: ShipmentWeightCheck) -> ShipmentWeightCheck:
        model = weight_check_to_model(check)
        self._session.add(model)
        self._flush()
        return weight_check_to_entity(model)

    def list_weight_checks(self, shipment_id: int) -> list[ShipmentWeightCheck]:
        statement = (
            select(ShipmentWeightCheckModel)
            .where(ShipmentWeightCheckModel.shipment_id == shipment_id)
            .order_by(ShipmentWeightCheckModel.checked_at, ShipmentWeightCheckModel.id)
        )
        return [weight_check_to_entity(model) for model in self._session.scalars(statement)]

    def _flush_identifiers(self) -> None:
        try:
            self._flush()
        except IntegrityError as error:
            detail = str(error).casefold()
            if "shipments.tracking_number_normalized" in detail:
                raise DuplicateShipmentNumberError("Shipment number is already reserved") from None
            raise

    def _flush(self) -> None:
        try:
            self._session.flush()
        except OperationalError as error:
            _raise_if_busy(error)
            raise


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _raise_if_busy(error: OperationalError) -> None:
    if "database is locked" in str(error).casefold():
        raise DatabaseBusyError("Database is busy; retry the operation") from None
