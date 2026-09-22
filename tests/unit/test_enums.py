"""Public enum values remain stable and centralized."""

from warehouse_control_center.domain.enums import ProblemType, ShipmentStatus, UserRole


def test_required_enum_values() -> None:
    assert {role.value for role in UserRole} == {
        "ADMIN",
        "WAREHOUSE_OPERATOR",
        "SUPERVISOR",
    }
    assert {status.value for status in ShipmentStatus} == {
        "RECEIVED",
        "SORTING",
        "READY_FOR_COURIER",
        "ASSIGNED",
        "DISPATCHED",
        "RETURNED",
        "PROBLEM",
    }
    assert {problem.value for problem in ProblemType} == {
        "DAMAGED",
        "WRONG_ADDRESS",
        "MISSING_DATA",
        "NOT_FOUND",
        "OTHER",
    }
