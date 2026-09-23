"""Canonical formatting policy for automatically allocated shipment numbers."""

from warehouse_control_center.domain.exceptions import ShipmentNumberExhaustedError

SHIPMENT_NUMBER_PREFIX = "E"
SHIPMENT_NUMBER_SEQUENCE_NAME = "shipment_number"
SHIPMENT_NUMBER_DIGITS = 9
SHIPMENT_NUMBER_MIN_VALUE = 1
SHIPMENT_NUMBER_MAX_VALUE = 999_999_999
SHIPMENT_NUMBER_EXHAUSTED_VALUE = SHIPMENT_NUMBER_MAX_VALUE + 1


def format_shipment_number(value: int) -> str:
    """Format a sequence value without permitting zero, overflow, or booleans."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not SHIPMENT_NUMBER_MIN_VALUE <= value <= SHIPMENT_NUMBER_MAX_VALUE
    ):
        raise ShipmentNumberExhaustedError("Shipment number capacity is exhausted")
    return f"{SHIPMENT_NUMBER_PREFIX}{value:0{SHIPMENT_NUMBER_DIGITS}d}"
