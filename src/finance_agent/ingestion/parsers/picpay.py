"""Adaptador do CSV exportado pelo PicPay."""

from pathlib import Path

from finance_agent.domain.enums import DataQualityCode
from finance_agent.domain.models import TransactionCandidate
from finance_agent.ingestion.models import CsvSchemaProfile, FormatSpec, ParserResult
from finance_agent.ingestion.parsers.utilities import (
    ParserValueError,
    direction_from_amount_text,
    direction_from_text,
    extraction_issue,
    file_identity,
    infer_payment_context,
    optional_value_warning,
    parse_date,
    parse_money,
    parse_time,
    read_csv_rows,
    record_hash,
    source_location,
    values_by_column,
)


class PicPayCsvParser:
    parser_id = "picpay_csv"

    def parse(
        self,
        path: Path,
        profile: CsvSchemaProfile,
        spec: FormatSpec,
    ) -> ParserResult:
        _, file_id = file_identity(path)
        candidates: list[TransactionCandidate] = []
        diagnostics = []
        rejected = 0
        rows = read_csv_rows(path, profile)

        for row_number, row in rows:
            if len(row) != len(profile.columns):
                rejected += 1
                diagnostics.append(
                    optional_value_warning(
                        row_number,
                        "A linha possui uma estrutura incompatível com o cabeçalho PicPay.",
                    )
                )
                continue

            values = values_by_column(row, profile.columns)
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

            amount_text = values.get(spec.mapping.amount or "", "")
            try:
                amount_minor = parse_money(amount_text)
            except ParserValueError:
                amount_minor = None
                issues.append(
                    extraction_issue(
                        DataQualityCode.INVALID_AMOUNT,
                        "amount_minor",
                        "O valor não pôde ser interpretado.",
                    )
                )

            time_text = values.get(spec.mapping.transaction_time or "", "")
            try:
                transaction_time = parse_time(time_text)
            except ParserValueError:
                transaction_time = None
                diagnostics.append(
                    optional_value_warning(
                        row_number,
                        "A hora opcional não pôde ser interpretada e foi ignorada.",
                    )
                )

            type_text = values.get(spec.mapping.direction or "", "")
            direction = direction_from_amount_text(amount_text) or direction_from_text(type_text)
            description = values.get(spec.mapping.description or "", "")
            payment_text = values.get(spec.mapping.payment_method or "", "")
            payment_method, payment_instrument = infer_payment_context(payment_text or type_text)

            candidates.append(
                TransactionCandidate(
                    transaction_date=transaction_date,
                    transaction_time=transaction_time,
                    amount_minor=amount_minor,
                    amount_direction=direction,
                    currency=spec.currency,
                    description_raw=description,
                    source_institution=spec.institution,
                    source_location=source_location(file_id, row_number),
                    source_record_hash=record_hash(row),
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
