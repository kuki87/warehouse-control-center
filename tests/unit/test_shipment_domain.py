"""Shipment validation, normalization, and workflow are centralized and exhaustive."""

import inspect

import pytest

from warehouse_control_center.application.services import ShipmentService
from warehouse_control_center.domain.entities import Shipment
from warehouse_control_center.domain.enums import ProblemType, ShipmentStatus
from warehouse_control_center.domain.exceptions import (
    InvalidShipmentError,
    InvalidShipmentTransitionError,
)
from warehouse_control_center.domain.normalization import normalize_tracking_number
from warehouse_control_center.domain.shipment_validation import (
    NOTES_MAX_LENGTH,
    validate_problem,
    validate_status_reason,
)
from warehouse_control_center.domain.shipment_workflow import (
    NORMAL_TRANSITIONS,
    can_recover,
    can_transition,
    require_transition,
)


def _shipment(**overrides: object) -> Shipment:
    values: dict[str, object] = {
        "tracking_number": "ABC-123",
        "barcode": "BAR-123",
        "recipient_name": "Željko Šarić",
        "recipient_address": "Ćirila i Metodija 10/2",
        "recipient_city": "Banja Luka",
        "recipient_phone": "+387 (65) 123-456",
        "sender_name": "Đorđe Čavić",
        "created_by": 1,
    }
    values.update(overrides)
    return Shipment(**values)  # type: ignore[arg-type]


def test_unicode_and_business_punctuation_are_preserved() -> None:
    shipment = _shipment(notes="Pažljivo!\nUlaz #2")

    assert shipment.recipient_name == "Željko Šarić"
    assert shipment.recipient_address == "Ćirila i Metodija 10/2"
    assert shipment.sender_name == "Đorđe Čavić"
    assert shipment.notes == "Pažljivo!\nUlaz #2"
    assert normalize_tracking_number(" ABC-123 ") == "ABC-123"
    assert normalize_tracking_number("ABC-123") != normalize_tracking_number("ABC123")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tracking_number", "  ", "Tracking number is required"),
        ("barcode", "", "Barcode is required"),
        ("recipient_name", "", "Recipient name is required"),
        ("recipient_address", "", "Recipient address is required"),
        ("recipient_city", "", "Recipient city is required"),
        ("recipient_phone", "12", "at least 3"),
        ("recipient_phone", "+387 CALL", "unsupported characters"),
        ("sender_name", "Name\x00", "control characters"),
        ("notes", "x" * (NOTES_MAX_LENGTH + 1), "at most"),
    ],
)
def test_invalid_shipment_fields_are_rejected(field: str, value: str, message: str) -> None:
    with pytest.raises(InvalidShipmentError, match=message):
        _shipment(**{field: value})


def test_every_normal_transition_and_rejection_matches_the_matrix() -> None:
    for current in ShipmentStatus:
        for target in ShipmentStatus:
            expected = target in NORMAL_TRANSITIONS[current]
            assert can_transition(current, target) is expected
            if expected:
                require_transition(current, target)
            else:
                with pytest.raises(InvalidShipmentTransitionError):
                    require_transition(current, target)


def test_problem_recovery_allows_previous_or_normal_non_problem_successor() -> None:
    assert can_recover(ShipmentStatus.SORTING, ShipmentStatus.SORTING)
    assert can_recover(ShipmentStatus.SORTING, ShipmentStatus.READY_FOR_COURIER)
    assert not can_recover(ShipmentStatus.SORTING, ShipmentStatus.DISPATCHED)
    assert not can_recover(ShipmentStatus.SORTING, ShipmentStatus.PROBLEM)


def test_other_problem_and_admin_override_require_explanations() -> None:
    with pytest.raises(InvalidShipmentError, match="description"):
        validate_problem(ProblemType.OTHER, " ")
    assert validate_problem(ProblemType.DAMAGED, None) == (ProblemType.DAMAGED, None)
    with pytest.raises(InvalidShipmentError, match="override reason"):
        validate_status_reason(None, required=True)


def test_generic_update_signature_cannot_mutate_workflow_or_assignment_fields() -> None:
    parameters = inspect.signature(ShipmentService.update_shipment).parameters
    assert "status" not in parameters
    assert "courier_id" not in parameters
    assert "created_by" not in parameters
