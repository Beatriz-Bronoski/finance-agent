import pytest

from finance_agent.domain.enums import TransactionDirection
from finance_agent.ingestion.parsers.utilities import (
    ParserValueError,
    direction_from_text,
    parse_date,
    parse_money,
)


@pytest.mark.parametrize(
    ("raw", "minor"),
    [
        ("R$ 1.500,00", 150000),
        ("−R$ 48,75", -4875),
        ("$1,234.56", 123456),
        ("(10.25)", -1025),
        ("250", 25000),
    ],
)
def test_money_parser_supports_common_locales(raw: str, minor: int) -> None:
    assert parse_money(raw) == minor


def test_money_parser_rejects_non_numeric_content() -> None:
    with pytest.raises(ParserValueError):
        parse_money("R$ XX")


def test_direction_inference_is_conservative_for_transfers() -> None:
    assert direction_from_text("Crédito recebido") == TransactionDirection.INFLOW
    assert direction_from_text("Pagamento") == TransactionDirection.OUTFLOW
    assert direction_from_text("Transferência") is None


def test_date_parser_rejects_ambiguous_international_date() -> None:
    with pytest.raises(ParserValueError):
        parse_date("03/04/2026")

    assert parse_date("13/08/2026").isoformat() == "2026-08-13"
    assert parse_date("08/13/2026").isoformat() == "2026-08-13"
    assert parse_date("03/04/2026", "dmy").isoformat() == "2026-04-03"
