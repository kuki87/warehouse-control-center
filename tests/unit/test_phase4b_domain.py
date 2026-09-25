"""Phase 4B exact money and payment/service domain policy tests."""

from decimal import Decimal

import pytest

from warehouse_control_center.domain.enums import (
    AdditionalServiceType,
    PaymentMethod,
    ShipmentPayer,
)
from warehouse_control_center.domain.exceptions import InvalidShipmentError
from warehouse_control_center.domain.payment import (
    MAX_MONEY_FEN,
    bam_to_fen,
    fen_to_bam,
    validate_payment,
)


def test_exact_bam_conversion_without_binary_float() -> None:
    assert bam_to_fen("1", "Amount", allow_zero=True) == 100
    assert bam_to_fen(Decimal("12.50"), "Amount", allow_zero=True) == 1_250
    assert bam_to_fen("0.01", "Amount", allow_zero=True) == 1
    assert fen_to_bam(1_250) == Decimal("12.5")
    with pytest.raises(InvalidShipmentError, match="two decimal"):
        bam_to_fen("12.501", "Amount", allow_zero=True)
    with pytest.raises(InvalidShipmentError, match="exact decimal"):
        bam_to_fen(12.5, "Amount", allow_zero=True)


@pytest.mark.parametrize("value", ["-0.01", Decimal("NaN"), MAX_MONEY_FEN + 1])
def test_money_rejects_negative_nonfinite_and_oversized_values(value: object) -> None:
    with pytest.raises(InvalidShipmentError):
        bam_to_fen(value, "Amount", allow_zero=True)


def test_cod_states_are_consistent() -> None:
    valid = validate_payment(
        declared_value_fen=None,
        cod_enabled=True,
        cod_amount_fen=1,
        payer=ShipmentPayer.RECIPIENT,
        payment_method=PaymentMethod.CASH,
        services=(),
    )
    assert valid.cod_amount_fen == 1
    for enabled, amount in ((True, None), (True, 0), (False, 100)):
        with pytest.raises(InvalidShipmentError):
            validate_payment(
                declared_value_fen=None,
                cod_enabled=enabled,
                cod_amount_fen=amount,
                payer=None,
                payment_method=None,
                services=(),
            )


def test_payment_rejects_invalid_enums_and_duplicate_services() -> None:
    base = {
        "declared_value_fen": None,
        "cod_enabled": False,
        "cod_amount_fen": None,
        "payer": None,
        "payment_method": None,
        "services": (),
    }
    with pytest.raises(InvalidShipmentError, match="payer"):
        validate_payment(**(base | {"payer": "SENDER"}))
    with pytest.raises(InvalidShipmentError, match="payment method"):
        validate_payment(**(base | {"payment_method": "CASH"}))
    with pytest.raises(InvalidShipmentError, match="Duplicate"):
        validate_payment(
            **(
                base
                | {
                    "services": (
                        AdditionalServiceType.EXPRESS,
                        AdditionalServiceType.EXPRESS,
                    )
                }
            )
        )
    with pytest.raises(InvalidShipmentError, match="Unsupported"):
        validate_payment(**(base | {"services": ("SMS",)}))


def test_insurance_requires_positive_declared_value_but_deselection_preserves_it() -> None:
    with pytest.raises(InvalidShipmentError, match="Insurance"):
        validate_payment(
            declared_value_fen=0,
            cod_enabled=False,
            cod_amount_fen=None,
            payer=None,
            payment_method=None,
            services=(AdditionalServiceType.INSURANCE,),
        )
    payment = validate_payment(
        declared_value_fen=5_000,
        cod_enabled=False,
        cod_amount_fen=None,
        payer=ShipmentPayer.SENDER,
        payment_method=PaymentMethod.INVOICE,
        services=(),
    )
    assert payment.declared_value_fen == 5_000
