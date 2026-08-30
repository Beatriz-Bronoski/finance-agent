"""Contrato comum para adaptadores de extrato."""

from pathlib import Path
from typing import Protocol

from finance_agent.ingestion.models import CsvSchemaProfile, FormatSpec, ParserResult


class StatementParser(Protocol):
    parser_id: str

    def parse(
        self,
        path: Path,
        profile: CsvSchemaProfile,
        spec: FormatSpec,
    ) -> ParserResult: ...
