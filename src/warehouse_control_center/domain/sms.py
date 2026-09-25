"""Validation and templates for append-only shipment SMS events."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from warehouse_control_center.domain.enums import (
    SmsMessageType,
    SmsSenderType,
    SmsSendStatus,
)
from warehouse_control_center.domain.exceptions import InvalidShipmentError, InvalidSmsError
from warehouse_control_center.domain.shipment_validation import validate_phone

SMS_MESSAGE_MAX_LENGTH = 1_000
SMS_ERROR_MAX_LENGTH = 1_000
SMS_PROVIDER_ID_MAX_LENGTH = 255
_HTML_TAG = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")


def default_sms_text(
    message_type: SmsMessageType,
    *,
    shipment_number: str,
    recipient_name: str,
) -> str | None:
    templates = {
        SmsMessageType.ARRIVAL_NOTIFICATION: (
            f"Hello {recipient_name}, shipment {shipment_number} has arrived at our warehouse."
        ),
        SmsMessageType.COURIER_NOTIFICATION: (
            f"Hello {recipient_name}, shipment {shipment_number} has been assigned for delivery."
        ),
        SmsMessageType.DELIVERY_ATTEMPT: (
            f"We attempted delivery of shipment {shipment_number}. Please contact the warehouse."
        ),
        SmsMessageType.READY_FOR_PICKUP: (f"Shipment {shipment_number} is ready for pickup."),
        SmsMessageType.ADDRESS_PROBLEM: (
            f"Address confirmation is required for shipment {shipment_number}."
        ),
    }
    return templates.get(message_type)


def validate_sms_event(
    *,
    sender_type: object,
    sent_by_user_id: object | None,
    phone_number: object,
    message_type: object,
    message_text: object | None,
    send_status: object,
    sent_at: datetime,
    delivered_at: datetime | None = None,
    provider_message_id: object | None = None,
    error_message: object | None = None,
) -> tuple[
    SmsSenderType,
    int | None,
    str,
    SmsMessageType,
    str,
    SmsSendStatus,
    str | None,
    str | None,
]:
    if not isinstance(sender_type, SmsSenderType):
        raise InvalidSmsError("Unsupported SMS sender type")
    if sender_type is SmsSenderType.SYSTEM:
        if sent_by_user_id is not None:
            raise InvalidSmsError("System SMS events must not reference a user sender")
        user_id = None
    elif isinstance(sent_by_user_id, bool) or not isinstance(sent_by_user_id, int):
        raise InvalidSmsError("Warehouse and courier SMS events require a user sender")
    elif sent_by_user_id < 1:
        raise InvalidSmsError("SMS sender user id must be positive")
    else:
        user_id = sent_by_user_id
    try:
        phone = validate_phone(phone_number)  # type: ignore[arg-type]
    except InvalidShipmentError as error:
        raise InvalidSmsError(str(error).replace("Recipient phone", "SMS phone")) from None
    if not isinstance(message_type, SmsMessageType):
        raise InvalidSmsError("Unsupported SMS message type")
    if not isinstance(send_status, SmsSendStatus):
        raise InvalidSmsError("Unsupported SMS send status")
    if message_type is SmsMessageType.CUSTOM and (
        not isinstance(message_text, str) or not message_text.strip()
    ):
        raise InvalidSmsError("Custom SMS message text is required")
    text = _required_text("SMS message", message_text, SMS_MESSAGE_MAX_LENGTH)
    if _HTML_TAG.search(text):
        raise InvalidSmsError("SMS message must not contain HTML")
    provider_id = _optional_text(
        "Provider message id", provider_message_id, SMS_PROVIDER_ID_MAX_LENGTH
    )
    failure_text = _optional_text("SMS error", error_message, SMS_ERROR_MAX_LENGTH)
    if sent_at.tzinfo is None or sent_at.utcoffset() is None:
        raise InvalidSmsError("SMS sent time must be timezone-aware")
    if delivered_at is not None:
        if delivered_at.tzinfo is None or delivered_at.utcoffset() is None:
            raise InvalidSmsError("SMS delivery time must be timezone-aware")
        if delivered_at < sent_at:
            raise InvalidSmsError("SMS delivery time cannot precede sent time")
    if send_status is SmsSendStatus.DELIVERED and delivered_at is None:
        raise InvalidSmsError("Delivered SMS events require a delivery time")
    if send_status is not SmsSendStatus.DELIVERED and delivered_at is not None:
        raise InvalidSmsError("Only delivered SMS events may have a delivery time")
    if send_status is SmsSendStatus.FAILED and failure_text is None:
        raise InvalidSmsError("Failed SMS events require an error message")
    return (
        sender_type,
        user_id,
        phone,
        message_type,
        text,
        send_status,
        provider_id,
        failure_text,
    )


def _required_text(label: str, value: object | None, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidSmsError(f"{label} is required")
    canonical = unicodedata.normalize("NFKC", value).strip()
    if not canonical:
        raise InvalidSmsError(f"{label} is required")
    if len(canonical) > maximum:
        raise InvalidSmsError(f"{label} must contain at most {maximum} characters")
    if any(unicodedata.category(character).startswith("C") for character in canonical):
        raise InvalidSmsError(f"{label} must not contain control characters")
    return canonical


def _optional_text(label: str, value: object | None, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidSmsError(f"{label} must be text")
    canonical = unicodedata.normalize("NFKC", value).strip()
    if not canonical:
        return None
    if len(canonical) > maximum:
        raise InvalidSmsError(f"{label} must contain at most {maximum} characters")
    if any(unicodedata.category(character).startswith("C") for character in canonical):
        raise InvalidSmsError(f"{label} must not contain control characters")
    return canonical
