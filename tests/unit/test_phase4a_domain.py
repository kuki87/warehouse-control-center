"""Phase 4A client and exact-measurement domain policies."""

from datetime import date
from decimal import Decimal

import pytest

from warehouse_control_center.domain.entities import Client
from warehouse_control_center.domain.enums import WeightCheckResult
from warehouse_control_center.domain.exceptions import InvalidClientError, InvalidShipmentError
from warehouse_control_center.domain.measurements import (
    MAX_STORED_MEASUREMENT,
    WeightTolerancePolicy,
    dimension_cm_to_mm,
    dimension_mm_to_cm,
    validate_dimension_cm,
    validate_package_count,
    validate_weight_g,
)


def test_client_unicode_whitespace_and_code_normalization() -> None:
    client = Client(
        client_code="  \u010c 001 ",
        company_name="  \u017duti \u010cempres d.o.o. ",
        address=" Ulica 1 ",
        city=" Sarajevo ",
    )
    assert client.client_code == "Č 001"
    assert client.client_code_normalized == "č001"
    assert client.company_name == "Žuti Čempres d.o.o."


def test_client_rejects_controls_invalid_email_and_contract_dates() -> None:
    base = {
        "client_code": "C-1",
        "company_name": "Company",
        "address": "Address",
        "city": "City",
    }
    with pytest.raises(InvalidClientError, match="control"):
        Client(**(base | {"company_name": "Bad\x00Name"}))
    with pytest.raises(InvalidClientError, match="Email"):
        Client(**base, email="invalid")
    with pytest.raises(InvalidClientError, match="before"):
        Client(**base, contract_start=date(2026, 2, 1), contract_end=date(2026, 1, 1))


@pytest.mark.parametrize("value", [0, -1, True, Decimal("1.2")])
def test_package_count_rejects_nonpositive_and_noninteger_values(value: object) -> None:
    with pytest.raises(InvalidShipmentError):
        validate_package_count(value)


def test_dimensions_are_exact_integer_millimeters() -> None:
    value = validate_dimension_cm("Length", Decimal("10.2"))
    assert value == Decimal("10.2")
    assert dimension_cm_to_mm(value) == 102
    assert dimension_mm_to_cm(102) == Decimal("10.2")
    for invalid in (Decimal("0"), Decimal("-1"), Decimal("1.23"), 1.2):
        with pytest.raises(InvalidShipmentError):
            validate_dimension_cm("Length", invalid)
    with pytest.raises(InvalidShipmentError, match="capacity"):
        validate_dimension_cm("Length", Decimal(MAX_STORED_MEASUREMENT + 1))


def test_weights_are_positive_bounded_integer_grams() -> None:
    assert validate_weight_g("Weight", 10_250, required=True) == 10_250
    assert validate_weight_g("Weight", None, required=False) is None
    for invalid in (None, 0, -1, True, Decimal("10")):
        with pytest.raises(InvalidShipmentError):
            validate_weight_g("Weight", invalid, required=True)
    with pytest.raises(InvalidShipmentError, match="capacity"):
        validate_weight_g("Weight", MAX_STORED_MEASUREMENT + 1, required=True)


def test_absolute_weight_tolerance_boundaries() -> None:
    policy = WeightTolerancePolicy(absolute_tolerance_g=100)
    assert policy.evaluate(1_000, 1_000) == (0, WeightCheckResult.MATCH)
    assert policy.evaluate(1_000, 900) == (100, WeightCheckResult.UNDER_TOLERANCE)
    assert policy.evaluate(1_000, 1_100) == (100, WeightCheckResult.UNDER_TOLERANCE)
    assert policy.evaluate(1_000, 1_101) == (101, WeightCheckResult.OVER_TOLERANCE)
