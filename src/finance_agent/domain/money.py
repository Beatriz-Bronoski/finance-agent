"""Conversão monetária segura, sem uso de ponto flutuante binário."""

from decimal import Decimal, InvalidOperation

from finance_agent.domain.enums import TransactionDirection


class MoneyConversionError(ValueError):
    """Valor monetário não pode ser convertido sem perda."""


class AmountDirectionError(ValueError):
    """Sinal e direção do valor são insuficientes ou conflitantes."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def decimal_to_minor(value: Decimal | str, exponent: int = 2) -> int:
    """Converte Decimal/string para a menor unidade (centavos, por padrão).

    Floats são recusados para impedir que imprecisões binárias entrem no domínio.
    Valores com casas excedentes também são recusados, em vez de arredondados.
    """

    if isinstance(value, bool) or not isinstance(value, (Decimal, str)):
        raise MoneyConversionError("use Decimal ou string para valores monetários")
    if exponent < 0:
        raise MoneyConversionError("o expoente monetário não pode ser negativo")

    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(value.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise MoneyConversionError("valor monetário inválido") from exc

    if not decimal_value.is_finite():
        raise MoneyConversionError("valor monetário deve ser finito")

    factor = Decimal(10) ** exponent
    scaled = decimal_value * factor
    if scaled != scaled.to_integral_value():
        raise MoneyConversionError("valor possui casas decimais além da moeda")
    return int(scaled)


def normalize_signed_amount(
    amount_minor: int,
    direction: TransactionDirection | None,
) -> int:
    """Normaliza saídas como negativas e entradas como positivas.

    Um valor negativo já identifica uma saída. Um valor positivo sem direção é
    ambíguo, porque alguns extratos publicam débitos e créditos sem sinal.
    """

    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise TypeError("amount_minor deve ser inteiro")
    if amount_minor == 0:
        raise AmountDirectionError("zero_amount")
    if direction == TransactionDirection.OUTFLOW:
        return -abs(amount_minor)
    if direction == TransactionDirection.INFLOW:
        if amount_minor < 0:
            raise AmountDirectionError("conflicting_amount_direction")
        return amount_minor
    if amount_minor < 0:
        return amount_minor
    raise AmountDirectionError("ambiguous_amount_direction")
