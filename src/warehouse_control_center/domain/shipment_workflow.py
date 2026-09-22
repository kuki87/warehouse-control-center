"""Single authoritative shipment status-transition policy."""

from warehouse_control_center.domain.enums import ShipmentStatus
from warehouse_control_center.domain.exceptions import InvalidShipmentTransitionError

NORMAL_TRANSITIONS: dict[ShipmentStatus, frozenset[ShipmentStatus]] = {
    ShipmentStatus.RECEIVED: frozenset({ShipmentStatus.SORTING, ShipmentStatus.PROBLEM}),
    ShipmentStatus.SORTING: frozenset({ShipmentStatus.READY_FOR_COURIER, ShipmentStatus.PROBLEM}),
    ShipmentStatus.READY_FOR_COURIER: frozenset({ShipmentStatus.ASSIGNED, ShipmentStatus.PROBLEM}),
    ShipmentStatus.ASSIGNED: frozenset(
        {
            ShipmentStatus.DISPATCHED,
            ShipmentStatus.READY_FOR_COURIER,
            ShipmentStatus.PROBLEM,
        }
    ),
    ShipmentStatus.DISPATCHED: frozenset({ShipmentStatus.RETURNED}),
    ShipmentStatus.RETURNED: frozenset({ShipmentStatus.SORTING, ShipmentStatus.PROBLEM}),
    ShipmentStatus.PROBLEM: frozenset(),
}


def can_transition(current: ShipmentStatus, target: ShipmentStatus) -> bool:
    return target in NORMAL_TRANSITIONS.get(current, frozenset())


def require_transition(current: ShipmentStatus, target: ShipmentStatus) -> None:
    if not can_transition(current, target):
        raise InvalidShipmentTransitionError(
            f"Shipment cannot transition from {current.value} to {target.value}"
        )


def can_recover(previous: ShipmentStatus, target: ShipmentStatus) -> bool:
    """Allow recovery to the captured state or one normal non-problem successor."""
    return target is previous or (
        target is not ShipmentStatus.PROBLEM and can_transition(previous, target)
    )


def require_recovery(previous: ShipmentStatus, target: ShipmentStatus) -> None:
    if not can_recover(previous, target):
        raise InvalidShipmentTransitionError(
            f"Problem reported from {previous.value} cannot recover to {target.value}"
        )
