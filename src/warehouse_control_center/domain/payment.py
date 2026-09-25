"""Exact BAM money conversion and shipment payment/service invariants."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from warehouse_control_center.domain.enums import (
    AdditionalServiceType,
    PaymentMethod,
    ShipmentPayer,
)
from warehouse_control_center.domain.exceptions import InvalidShipmentError

BAM_MINOR_UNITS = 100
MAX_MONEY_FEN = 2_147_483_647


def bam_to_fen(value: object | None, label: str, *, allow_zero: bool) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise InvalidShipmentError(f"{label} must be an exact decimal BAM value")
    try:
        amount = Decimal(value) if isinstance(value, (str, int)) else value
    except (InvalidOperation, ValueError):
        raise InvalidShipmentError(f"{label} must be a valid BAM value") from None
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise InvalidShipmentError(f"{label} must be a valid BAM value")
    fen = amount * BAM_MINOR_UNITS
    if fen != fen.to_integral_value():
        raise InvalidShipmentError(f"{label} supports at most two decimal places")
    minimum = 0 if allow_zero else 1
    if fen < minimum:
        comparison = "zero or greater" if allow_zero else "greater than zero"
        raise InvalidShipmentError(f"{label} must be {comparison}")
    if fen > MAX_MONEY_FEN:
        raise InvalidShipmentError(f"{label} exceeds storage capacity")
    return int(fen)


def fen_to_bam(value: int | None) -> Decimal | None:
    return Decimal(value) / BAM_MINOR_UNITS if value is not None else None


def validate_money_fen(label: str, value: object | None, *, allow_zero: bool) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidShipmentError(f"{label} must use whole fenings")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        comparison = "zero or greater" if allow_zero else "greater than zero"
        raise InvalidShipmentError(f"{label} must be {comparison}")
    if value > MAX_MONEY_FEN:
        raise InvalidShipmentError(f"{label} exceeds storage capacity")
    return value


def normalize_services(values: Iterable[object]) -> frozenset[AdditionalServiceType]:
    services: set[AdditionalServiceType] = set()
    for value in values:
        if not isinstance(value, AdditionalServiceType):
            raise InvalidShipmentError("Unsupported additional service type")
        if value in services:
            raise InvalidShipmentError(f"Duplicate additional service: {value.value}")
        services.add(value)
    return frozenset(services)


@dataclass(frozen=True, slots=True)
class ValidatedPayment:
    declared_value_fen: int | None
    cod_enabled: bool
    cod_amount_fen: int | None
    payer: ShipmentPayer | None
    payment_method: PaymentMethod | None
    services: frozenset[AdditionalServiceType]


def validate_payment(
    *,
    declared_value_fen: object | None,
    cod_enabled: object,
    cod_amount_fen: object | None,
    payer: object | None,
    payment_method: object | None,
    services: Iterable[object],
) -> ValidatedPayment:
    if not isinstance(cod_enabled, bool):
        raise InvalidShipmentError("COD enabled must be a boolean")
    declared = validate_money_fen("Declared value", declared_value_fen, allow_zero=True)
    cod_amount = validate_money_fen("COD amount", cod_amount_fen, allow_zero=False)
    if cod_enabled and cod_amount is None:
        raise InvalidShipmentError("COD amount is required when COD is enabled")
    if not cod_enabled and cod_amount is not None:
        raise InvalidShipmentError("COD amount must be absent when COD is disabled")
    if payer is not None and not isinstance(payer, ShipmentPayer):
        raise InvalidShipmentError("Unsupported shipment payer")
    if payment_method is not None and not isinstance(payment_method, PaymentMethod):
        raise InvalidShipmentError("Unsupported payment method")
    normalized_services = normalize_services(services)
    if AdditionalServiceType.INSURANCE in normalized_services and (
        declared is None or declared <= 0
    ):
        raise InvalidShipmentError("Insurance requires a declared value greater than zero")
    return ValidatedPayment(
        declared_value_fen=declared,
        cod_enabled=cod_enabled,
        cod_amount_fen=cod_amount,
        payer=payer,
        payment_method=payment_method,
        services=normalized_services,
    )
