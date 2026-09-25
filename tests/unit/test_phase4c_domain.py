"""Phase 4C SMS event validation tests."""

from datetime import UTC, datetime

import pytest

from warehouse_control_center.domain.entities import ShipmentSmsEvent
from warehouse_control_center.domain.enums import (
    SmsMessageType,
    SmsSenderType,
    SmsSendStatus,
)
from warehouse_control_center.domain.exceptions import InvalidSmsError
from warehouse_control_center.domain.sms import default_sms_text


def _event(**overrides: object) -> ShipmentSmsEvent:
    values: dict[str, object] = {
        "shipment_id": 1,
        "sender_type": SmsSenderType.WAREHOUSE,
        "sent_by_user_id": 2,
        "phone_number": "+387 65 123 456",
        "message_type": SmsMessageType.CUSTOM,
        "message_text": "Pošiljka je evidentirana — hvala.",
        "send_status": SmsSendStatus.RECORDED,
        "sent_at": datetime(2026, 1, 1, tzinfo=UTC),
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return ShipmentSmsEvent(**values)  # type: ignore[arg-type]


def test_unicode_sms_and_centralized_templates() -> None:
    event = _event()
    assert event.message_text == "Pošiljka je evidentirana — hvala."
    assert (
        default_sms_text(
            SmsMessageType.READY_FOR_PICKUP,
            shipment_number="E000000001",
            recipient_name="Željko",
        )
        == "Shipment E000000001 is ready for pickup."
    )
    assert (
        default_sms_text(
            SmsMessageType.CUSTOM,
            shipment_number="E000000001",
            recipient_name="Željko",
        )
        is None
    )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("sender_type", "WAREHOUSE", "sender type"),
        ("message_type", "CUSTOM", "message type"),
        ("send_status", "RECORDED", "send status"),
        ("phone_number", "not-a-phone", "SMS phone"),
        ("message_text", "bad\x00text", "control characters"),
        ("message_text", "<b>unsafe</b>", "HTML"),
    ],
)
def test_sms_rejects_invalid_types_phone_and_message(field: str, value: object, match: str) -> None:
    with pytest.raises(InvalidSmsError, match=match):
        _event(**{field: value})


def test_custom_text_and_sender_identity_rules() -> None:
    with pytest.raises(InvalidSmsError, match="Custom SMS message text"):
        _event(message_text="  ")
    with pytest.raises(InvalidSmsError, match="require a user sender"):
        _event(sent_by_user_id=None)
    system = _event(sender_type=SmsSenderType.SYSTEM, sent_by_user_id=None)
    assert system.sent_by_user_id is None
    with pytest.raises(InvalidSmsError, match="must not reference"):
        _event(sender_type=SmsSenderType.SYSTEM, sent_by_user_id=2)


def test_delivery_and_failure_states_require_evidence() -> None:
    with pytest.raises(InvalidSmsError, match="delivery time"):
        _event(send_status=SmsSendStatus.DELIVERED)
    with pytest.raises(InvalidSmsError, match="error message"):
        _event(send_status=SmsSendStatus.FAILED)
    delivered = _event(
        send_status=SmsSendStatus.DELIVERED,
        delivered_at=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
    )
    assert delivered.delivered_at is not None
