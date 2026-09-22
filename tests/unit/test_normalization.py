"""Identifier normalization is centralized and deterministic."""

import pytest

from warehouse_control_center.domain.normalization import (
    normalize_barcode,
    normalize_courier_code,
    normalize_tracking_number,
    normalize_username,
)


@pytest.mark.parametrize(
    ("normalizer", "left", "right"),
    [
        (normalize_username, "  ADMIN ", "admin"),
        (normalize_username, "ŽELJKO", "željko"),
        (normalize_username, "C\N{COMBINING ACUTE ACCENT}", "Ć"),
        (normalize_tracking_number, " ab 123 ", "AB123"),
        (normalize_tracking_number, "ＡＢＣ１２３", "ABC123"),
        (normalize_barcode, " bar 001 ", "BAR001"),
        (normalize_courier_code, " Č-1878 ", "č-1878"),
        (normalize_courier_code, " 1878 ", "1878"),
    ],
)
def test_equivalent_identifiers_normalize_to_same_value(
    normalizer: object, left: str, right: str
) -> None:
    assert callable(normalizer)
    assert normalizer(left) == normalizer(right)


def test_identifier_whitespace_collides_but_punctuation_is_preserved() -> None:
    assert normalize_tracking_number("ABC 123") == normalize_tracking_number("ABC123")
    assert normalize_tracking_number("ABC-123") != normalize_tracking_number("ABC123")
    assert normalize_barcode("abc-123") == "ABC-123"
