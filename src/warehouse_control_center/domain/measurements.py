"""Exact shipment measurement validation and control-weight policy."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from warehouse_control_center.domain.enums import WeightCheckResult
from warehouse_control_center.domain.exceptions import InvalidShipmentError

MAX_STORED_MEASUREMENT = 2_147_483_647
DEFAULT_WEIGHT_TOLERANCE_G = 100


def validate_package_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidShipmentError("Package count must be a positive integer")
    if value > MAX_STORED_MEASUREMENT:
        raise InvalidShipmentError("Package count exceeds storage capacity")
    return value


def validate_dimension_cm(label: str, value: object | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise InvalidShipmentError(f"{label} must be an exact decimal value")
    try:
        decimal_value = Decimal(value) if isinstance(value, (str, int)) else value
    except (InvalidOperation, ValueError):
        raise InvalidShipmentError(f"{label} must be a valid decimal value") from None
    if not isinstance(decimal_value, Decimal) or not decimal_value.is_finite():
        raise InvalidShipmentError(f"{label} must be a valid decimal value")
    if decimal_value <= 0:
        raise InvalidShipmentError(f"{label} must be greater than zero")
    millimeters = decimal_value * 10
    if millimeters != millimeters.to_integral_value():
        raise InvalidShipmentError(f"{label} supports at most one decimal place")
    if millimeters > MAX_STORED_MEASUREMENT:
        raise InvalidShipmentError(f"{label} exceeds storage capacity")
    return decimal_value.normalize()


def dimension_cm_to_mm(value: Decimal | None) -> int | None:
    return int(value * 10) if value is not None else None


def dimension_mm_to_cm(value: int | None) -> Decimal | None:
    return Decimal(value) / Decimal(10) if value is not None else None


def validate_weight_g(label: str, value: object | None, *, required: bool) -> int | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidShipmentError(f"{label} must be a positive whole number of grams")
    if value > MAX_STORED_MEASUREMENT:
        raise InvalidShipmentError(f"{label} exceeds storage capacity")
    return value


@dataclass(frozen=True, slots=True)
class WeightTolerancePolicy:
    absolute_tolerance_g: int = DEFAULT_WEIGHT_TOLERANCE_G

    def __post_init__(self) -> None:
        if self.absolute_tolerance_g < 0:
            raise ValueError("Weight tolerance must not be negative")

    def evaluate(
        self, declared_weight_g: int, measured_weight_g: int
    ) -> tuple[int, WeightCheckResult]:
        difference = abs(measured_weight_g - declared_weight_g)
        if difference == 0:
            result = WeightCheckResult.MATCH
        elif difference <= self.absolute_tolerance_g:
            result = WeightCheckResult.UNDER_TOLERANCE
        else:
            result = WeightCheckResult.OVER_TOLERANCE
        return difference, result
