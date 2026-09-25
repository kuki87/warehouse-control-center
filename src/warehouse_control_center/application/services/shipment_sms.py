"""Authorized append-only shipment SMS recording and history queries."""

from __future__ import annotations

from datetime import datetime

from warehouse_control_center.application.dto import (
    SessionContext,
    ShipmentSmsEventDTO,
    ShipmentSmsEventPage,
    ShipmentSmsSummaryDTO,
    ShipmentSmsSummaryPage,
)
from warehouse_control_center.application.ports.clock import Clock
from warehouse_control_center.application.ports.repositories import (
    ShipmentSmsListQuery,
    SmsEventListQuery,
)
from warehouse_control_center.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from warehouse_control_center.application.services._actor import require_current_actor
from warehouse_control_center.application.services._audit import make_audit_event
from warehouse_control_center.application.services._time import utc_timestamp
from warehouse_control_center.domain.entities import Shipment, ShipmentSmsEvent, User
from warehouse_control_center.domain.enums import (
    AuditAction,
    Permission,
    SmsMessageType,
    SmsSenderType,
    SmsSendStatus,
)
from warehouse_control_center.domain.exceptions import (
    InvalidShipmentQueryError,
    ShipmentArchivedError,
    ShipmentNotFoundError,
)
from warehouse_control_center.domain.shipment_validation import validate_search_text
from warehouse_control_center.domain.sms import default_sms_text

DEFAULT_SMS_PAGE_SIZE = 50
MAX_SMS_PAGE_SIZE = 100


class ShipmentSmsService:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    def record_sms(
        self,
        session: SessionContext,
        shipment_id: int,
        *,
        sender_type: SmsSenderType,
        message_type: SmsMessageType,
        phone_number: str | None = None,
        message_text: str | None = None,
        send_status: SmsSendStatus = SmsSendStatus.RECORDED,
        delivered_at: datetime | None = None,
        provider_message_id: str | None = None,
        error_message: str | None = None,
    ) -> ShipmentSmsEventDTO:
        with self._uow_factory() as uow:
            actor = require_current_actor(uow, session, Permission.RECORD_SHIPMENT_SMS)
            shipment = _get_shipment(uow, shipment_id)
            if shipment.archived_at is not None:
                raise ShipmentArchivedError("Archived shipments cannot record SMS events")
            resolved_text = message_text
            if resolved_text is None and isinstance(message_type, SmsMessageType):
                resolved_text = default_sms_text(
                    message_type,
                    shipment_number=shipment.shipment_number,
                    recipient_name=shipment.recipient_name,
                )
            now = utc_timestamp(self._clock.now())
            event = uow.shipment_sms.add(
                ShipmentSmsEvent(
                    shipment_id=shipment_id,
                    sender_type=sender_type,
                    sent_by_user_id=(
                        None if sender_type is SmsSenderType.SYSTEM else _persisted_id(actor)
                    ),
                    phone_number=(
                        shipment.recipient_phone if phone_number is None else phone_number
                    ),
                    message_type=message_type,
                    message_text=resolved_text or "",
                    send_status=send_status,
                    sent_at=now,
                    delivered_at=delivered_at,
                    provider_message_id=provider_message_id,
                    error_message=error_message,
                    created_at=now,
                )
            )
            uow.audits.add(
                make_audit_event(
                    action=AuditAction.SHIPMENT_SMS_RECORDED,
                    actor_id=_persisted_id(actor),
                    actor_name=actor.username,
                    entity_type="SHIPMENT_SMS",
                    entity_id=event.id or shipment_id,
                    timestamp=now,
                    details={
                        "shipment_number": shipment.shipment_number,
                        "sender_type": event.sender_type.value,
                        "message_type": event.message_type.value,
                        "phone_number": event.phone_number,
                        "send_status": event.send_status.value,
                    },
                )
            )
            uow.commit()
        return ShipmentSmsEventDTO.from_entity(event)

    def list_sms_for_shipment(
        self,
        session: SessionContext,
        shipment_id: int,
        *,
        page: int = 1,
        page_size: int = DEFAULT_SMS_PAGE_SIZE,
        sender_type: SmsSenderType | None = None,
        message_type: SmsMessageType | None = None,
        send_status: SmsSendStatus | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> ShipmentSmsEventPage:
        _validate_query(page, page_size, sender_type, message_type, send_status)
        start, end = _date_range(date_from, date_to)
        query = SmsEventListQuery(
            shipment_id=shipment_id,
            offset=(page - 1) * page_size,
            limit=page_size,
            sender_type=sender_type,
            message_type=message_type,
            send_status=send_status,
            date_from=start,
            date_to=end,
        )
        with self._uow_factory() as uow:
            require_current_actor(uow, session, Permission.VIEW_SHIPMENT_SMS)
            _get_shipment(uow, shipment_id)
            events, total = uow.shipment_sms.list_for_shipment(query)
        return ShipmentSmsEventPage(
            tuple(ShipmentSmsEventDTO.from_entity(event) for event in events),
            page,
            page_size,
            total,
        )

    def list_shipments_with_sms(
        self,
        session: SessionContext,
        *,
        page: int = 1,
        page_size: int = DEFAULT_SMS_PAGE_SIZE,
        search: str | None = None,
        sender_type: SmsSenderType | None = None,
        message_type: SmsMessageType | None = None,
        send_status: SmsSendStatus | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> ShipmentSmsSummaryPage:
        _validate_query(page, page_size, sender_type, message_type, send_status)
        start, end = _date_range(date_from, date_to)
        query = ShipmentSmsListQuery(
            offset=(page - 1) * page_size,
            limit=page_size,
            search=validate_search_text(search),
            sender_type=sender_type,
            message_type=message_type,
            send_status=send_status,
            date_from=start,
            date_to=end,
        )
        with self._uow_factory() as uow:
            require_current_actor(uow, session, Permission.VIEW_SHIPMENT_SMS)
            summaries, total = uow.shipment_sms.list_shipments(query)
        return ShipmentSmsSummaryPage(
            tuple(ShipmentSmsSummaryDTO.from_entity(item) for item in summaries),
            page,
            page_size,
            total,
        )


def _get_shipment(uow: UnitOfWork, shipment_id: int) -> Shipment:
    if isinstance(shipment_id, bool) or not isinstance(shipment_id, int) or shipment_id < 1:
        raise ShipmentNotFoundError("Shipment does not exist")
    shipment = uow.shipments.get_by_id(shipment_id)
    if shipment is None:
        raise ShipmentNotFoundError("Shipment does not exist")
    return shipment


def _persisted_id(user: User) -> int:
    if user.id is None:
        raise RuntimeError("Authenticated user is not persisted")
    return user.id


def _validate_query(
    page: int,
    page_size: int,
    sender_type: object,
    message_type: object,
    send_status: object,
) -> None:
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise InvalidShipmentQueryError("Page must be a positive integer")
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= MAX_SMS_PAGE_SIZE
    ):
        raise InvalidShipmentQueryError(f"Page size must be between 1 and {MAX_SMS_PAGE_SIZE}")
    if sender_type is not None and not isinstance(sender_type, SmsSenderType):
        raise InvalidShipmentQueryError("Unsupported SMS sender filter")
    if message_type is not None and not isinstance(message_type, SmsMessageType):
        raise InvalidShipmentQueryError("Unsupported SMS message filter")
    if send_status is not None and not isinstance(send_status, SmsSendStatus):
        raise InvalidShipmentQueryError("Unsupported SMS status filter")


def _date_range(
    date_from: datetime | None, date_to: datetime | None
) -> tuple[datetime | None, datetime | None]:
    try:
        start = utc_timestamp(date_from) if date_from is not None else None
        end = utc_timestamp(date_to) if date_to is not None else None
    except ValueError as error:
        raise InvalidShipmentQueryError("SMS date filters must be timezone-aware") from error
    if start is not None and end is not None and start > end:
        raise InvalidShipmentQueryError("Date from must not be after date to")
    return start, end
