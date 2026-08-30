from decimal import Decimal

import pytest

from finance_agent.domain.enums import TransactionDirection
from finance_agent.domain.money import (
    AmountDirectionError,
    MoneyConversionError,
    decimal_to_minor,
    normalize_signed_amount,
)


def test_decimal_to_minor_preserves_cents() -> None:
    assert decimal_to_minor(Decimal("48.75")) == 4875
    assert decimal_to_minor("-12.30") == -1230


def test_decimal_to_minor_rejects_float_and_silent_rounding() -> None:
    with pytest.raises(MoneyConversionError):
        decimal_to_minor(48.75)  # type: ignore[arg-type]
    with pytest.raises(MoneyConversionError):
        decimal_to_minor("10.001")


def test_signed_amount_normalization() -> None:
    assert normalize_signed_amount(2500, TransactionDirection.OUTFLOW) == -2500
    assert normalize_signed_amount(-2500, TransactionDirection.OUTFLOW) == -2500
    assert normalize_signed_amount(2500, TransactionDirection.INFLOW) == 2500
    assert normalize_signed_amount(-2500, None) == -2500


@pytest.mark.parametrize(
    ("value", "direction", "expected_code"),
    [
        (0, None, "zero_amount"),
        (2500, None, "ambiguous_amount_direction"),
        (-2500, TransactionDirection.INFLOW, "conflicting_amount_direction"),
    ],
)
def test_signed_amount_rejects_unsafe_interpretation(
    value: int,
    direction: TransactionDirection | None,
    expected_code: str,
) -> None:
    with pytest.raises(AmountDirectionError) as error:
        normalize_signed_amount(value, direction)
    assert error.value.code == expected_code
