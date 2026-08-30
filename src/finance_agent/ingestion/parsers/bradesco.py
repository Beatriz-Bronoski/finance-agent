"""Adaptador tolerante às irregularidades do CSV Bradesco."""

from pathlib import Path

from finance_agent.domain.enums import DataQualityCode, TransactionDirection
from finance_agent.domain.models import TransactionCandidate
from finance_agent.domain.quality import normalize_description
from finance_agent.ingestion.models import (
    CsvSchemaProfile,
    FormatSpec,
    IngestionIssueCode,
    ParseDiagnostic,
    ParserResult,
)
from finance_agent.domain.enums import IssueSeverity
from finance_agent.ingestion.parsers.utilities import (
    ParserValueError,
    extraction_issue,
    file_identity,
    infer_payment_context,
    optional_value_warning,
    parse_date,
    parse_money,
    read_csv_rows,
    record_hash,
    source_location,
    values_by_column,
)


class BradescoCsvParser:
    parser_id = "bradesco_csv"

    @staticmethod
    def _values(row: list[str], profile: CsvSchemaProfile) -> dict[str, str]:
        if "historico" in profile.columns and len(row) > len(profile.columns):
            description_index = profile.columns.index("historico")
            extra_cells = len(row) - len(profile.columns)
            values: dict[str, str] = {}
            for index, column in enumerate(profile.columns):
                if index < description_index:
                    values[column] = row[index].strip()
                elif index == description_index:
                    end = index + extra_cells + 1
                    values[column] = "; ".join(
                        part.strip() for part in row[index:end] if part.strip()
                    )
                else:
                    values[column] = row[index + extra_cells].strip()
            return values
        return values_by_column(row, profile.columns)

    def parse(
        self,
        path: Path,
        profile: CsvSchemaProfile,
        spec: FormatSpec,
    ) -> ParserResult:
        _, file_id = file_identity(path)
        candidates: list[TransactionCandidate] = []
        diagnostics: list[ParseDiagnostic] = []
        rejected = 0
        rows = read_csv_rows(path, profile)

        for row_number, row in rows:
            values = self._values(row, profile)
            description = values.get(spec.mapping.description or "", "")
            credit_text = values.get(spec.mapping.credit or "", "")
            debit_text = values.get(spec.mapping.debit or "", "")

            if not credit_text and not debit_text and "SALDO ANTERIOR" in normalize_description(
                description
            ):
                rejected += 1
                diagnostics.append(
                    ParseDiagnostic(
                        code=IngestionIssueCode.NON_TRANSACTION_ROW,
                        severity=IssueSeverity.WARNING,
                        row_number=row_number,
                        message=(
                            "Uma linha informativa de saldo foi ignorada "
                            "como não transacional."
                        ),
                    )
                )
                continue

            issues = []
            try:
                transaction_date = parse_date(
                    values.get(spec.mapping.transaction_date or "", ""),
                    spec.date_order,
                )
            except ParserValueError:
                transaction_date = None
                issues.append(
                    extraction_issue(
                        DataQualityCode.INVALID_TRANSACTION_DATE,
                        "transaction_date",
                        "A data não pôde ser interpretada.",
                    )
                )

            amount_minor = None
            direction = None
            if credit_text and debit_text:
                issues.append(
                    extraction_issue(
                        DataQualityCode.INVALID_AMOUNT,
                        "amount_minor",
                        "Crédito e débito foram preenchidos na mesma linha.",
                    )
                )
            else:
                amount_text = credit_text or debit_text
                if amount_text:
                    try:
                        amount_minor = parse_money(amount_text)
                        direction = (
                            TransactionDirection.INFLOW
                            if credit_text
                            else TransactionDirection.OUTFLOW
                        )
                    except ParserValueError:
                        issues.append(
                            extraction_issue(
                                DataQualityCode.INVALID_AMOUNT,
                                "amount_minor",
                                "O valor não pôde ser interpretado.",
                            )
                        )

            balance_minor = None
            balance_text = values.get(spec.mapping.balance or "", "")
            if balance_text:
                try:
                    balance_minor = parse_money(balance_text)
                except ParserValueError:
                    diagnostics.append(
                        optional_value_warning(
                            row_number,
                            "O saldo opcional não pôde ser interpretado e foi ignorado.",
                        )
                    )

            payment_method, payment_instrument = infer_payment_context(description)
            candidates.append(
                TransactionCandidate(
                    transaction_date=transaction_date,
                    amount_minor=amount_minor,
                    amount_direction=direction,
                    currency=spec.currency,
                    description_raw=description,
                    source_institution=spec.institution,
                    source_location=source_location(file_id, row_number),
                    source_record_hash=record_hash(row),
                    external_id=values.get(spec.mapping.external_id or "", "") or None,
                    balance_minor=balance_minor,
                    payment_method=payment_method,
                    payment_instrument=payment_instrument,
                    extraction_issues=issues,
                )
            )

        return ParserResult(
            records_read=len(rows),
            candidates=candidates,
            rejected_count=rejected,
            diagnostics=diagnostics,
        )
