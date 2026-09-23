"""Visible shipment numbers retain their fixed-width domain format."""

import pytest

from warehouse_control_center.domain.exceptions import ShipmentNumberExhaustedError
from warehouse_control_center.domain.shipment_numbering import format_shipment_number


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, "E000000001"),
        (9, "E000000009"),
        (10, "E000000010"),
        (999, "E000000999"),
        (123_456_789, "E123456789"),
        (999_999_999, "E999999999"),
    ],
)
def test_format_shipment_number(value: int, expected: str) -> None:
    assert format_shipment_number(value) == expected


@pytest.mark.parametrize("value", [0, -1, 1_000_000_000, True])
def test_format_shipment_number_rejects_values_outside_capacity(value: int) -> None:
    with pytest.raises(ShipmentNumberExhaustedError):
        format_shipment_number(value)
