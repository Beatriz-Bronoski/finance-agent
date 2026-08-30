"""Seleção explícita de parsers suportados."""

from finance_agent.ingestion.models import FormatSpec
from finance_agent.ingestion.parsers.base import StatementParser
from finance_agent.ingestion.parsers.bradesco import BradescoCsvParser
from finance_agent.ingestion.parsers.generic import GenericCsvParser
from finance_agent.ingestion.parsers.picpay import PicPayCsvParser


def parser_for_spec(spec: FormatSpec) -> StatementParser:
    parsers: dict[str, StatementParser] = {
        PicPayCsvParser.parser_id: PicPayCsvParser(),
        BradescoCsvParser.parser_id: BradescoCsvParser(),
        GenericCsvParser.parser_id: GenericCsvParser(),
    }
    try:
        return parsers[spec.parser_id]
    except KeyError as exc:
        raise ValueError("O formato selecionado não possui um parser registrado.") from exc


__all__ = ["StatementParser", "parser_for_spec"]
