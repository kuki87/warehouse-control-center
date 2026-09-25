"""Append-only shipment SMS persistence and grouped shipment summaries."""

from sqlalchemy import func, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from warehouse_control_center.application.ports.repositories import (
    ShipmentSmsListQuery,
    SmsEventListQuery,
)
from warehouse_control_center.domain.entities import ShipmentSmsEvent, ShipmentSmsSummary
from warehouse_control_center.domain.exceptions import DatabaseBusyError
from warehouse_control_center.domain.normalization import normalize_shipment_number
from warehouse_control_center.infrastructure.database.models import (
    ShipmentModel,
    ShipmentSmsEventModel,
)
from warehouse_control_center.infrastructure.database.repositories.mapping import (
    shipment_to_entity,
    sms_event_to_entity,
    sms_event_to_model,
)


class SqlAlchemyShipmentSmsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: ShipmentSmsEvent) -> ShipmentSmsEvent:
        model = sms_event_to_model(event)
        self._session.add(model)
        try:
            self._session.flush()
        except OperationalError as error:
            if "database is locked" in str(error).casefold():
                raise DatabaseBusyError("Database is busy; retry the operation") from None
            raise
        return sms_event_to_entity(model)

    def list_for_shipment(self, query: SmsEventListQuery) -> tuple[list[ShipmentSmsEvent], int]:
        filters = self._event_filters(query)
        total = (
            self._session.scalar(
                select(func.count()).select_from(ShipmentSmsEventModel).where(*filters)
            )
            or 0
        )
        statement = (
            select(ShipmentSmsEventModel)
            .where(*filters)
            .order_by(ShipmentSmsEventModel.sent_at.desc(), ShipmentSmsEventModel.id.desc())
            .offset(query.offset)
            .limit(query.limit)
        )
        return [sms_event_to_entity(model) for model in self._session.scalars(statement)], total

    def list_shipments(self, query: ShipmentSmsListQuery) -> tuple[list[ShipmentSmsSummary], int]:
        event_filters = self._summary_event_filters(query)
        latest_id = (
            select(ShipmentSmsEventModel.id)
            .where(ShipmentSmsEventModel.shipment_id == ShipmentModel.id, *event_filters)
            .order_by(ShipmentSmsEventModel.sent_at.desc(), ShipmentSmsEventModel.id.desc())
            .limit(1)
            .correlate(ShipmentModel)
            .scalar_subquery()
        )
        sms_count = (
            select(func.count())
            .select_from(ShipmentSmsEventModel)
            .where(ShipmentSmsEventModel.shipment_id == ShipmentModel.id, *event_filters)
            .correlate(ShipmentModel)
            .scalar_subquery()
        )
        shipment_filters: list[ColumnElement[bool]] = [latest_id.is_not(None)]
        if query.search:
            term = query.search.strip()
            pattern = f"%{_escape_like(term)}%"
            shipment_filters.append(
                or_(
                    ShipmentModel.shipment_number_normalized.contains(
                        normalize_shipment_number(term), autoescape=True
                    ),
                    ShipmentModel.recipient_name.ilike(pattern, escape="\\"),
                    ShipmentModel.recipient_phone.ilike(pattern, escape="\\"),
                    ShipmentModel.recipient_city.ilike(pattern, escape="\\"),
                )
            )
        total = (
            self._session.scalar(
                select(func.count()).select_from(ShipmentModel).where(*shipment_filters)
            )
            or 0
        )
        statement = (
            select(ShipmentModel, sms_count, ShipmentSmsEventModel)
            .join(ShipmentSmsEventModel, ShipmentSmsEventModel.id == latest_id)
            .where(*shipment_filters)
            .order_by(ShipmentSmsEventModel.sent_at.desc(), ShipmentModel.id.asc())
            .offset(query.offset)
            .limit(query.limit)
        )
        return [
            ShipmentSmsSummary(
                shipment=shipment_to_entity(shipment),
                sms_count=count,
                last_event=sms_event_to_entity(last_event),
            )
            for shipment, count, last_event in self._session.execute(statement)
        ], total

    @staticmethod
    def _event_filters(query: SmsEventListQuery) -> list[ColumnElement[bool]]:
        return [
            ShipmentSmsEventModel.shipment_id == query.shipment_id,
            *SqlAlchemyShipmentSmsRepository._typed_filters(
                query.sender_type,
                query.message_type,
                query.send_status,
                query.date_from,
                query.date_to,
            ),
        ]

    @staticmethod
    def _summary_event_filters(query: ShipmentSmsListQuery) -> list[ColumnElement[bool]]:
        return SqlAlchemyShipmentSmsRepository._typed_filters(
            query.sender_type,
            query.message_type,
            query.send_status,
            query.date_from,
            query.date_to,
        )

    @staticmethod
    def _typed_filters(
        sender_type: object,
        message_type: object,
        send_status: object,
        date_from: object,
        date_to: object,
    ) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = []
        if sender_type is not None:
            filters.append(ShipmentSmsEventModel.sender_type == sender_type)
        if message_type is not None:
            filters.append(ShipmentSmsEventModel.message_type == message_type)
        if send_status is not None:
            filters.append(ShipmentSmsEventModel.send_status == send_status)
        if date_from is not None:
            filters.append(ShipmentSmsEventModel.sent_at >= date_from)
        if date_to is not None:
            filters.append(ShipmentSmsEventModel.sent_at <= date_to)
        return filters


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
