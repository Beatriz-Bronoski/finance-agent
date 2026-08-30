"""Parser configurável para formatos CSV aprovados pela pessoa usuária."""

from pathlib import Path

from finance_agent.domain.enums import DataQualityCode, TransactionDirection
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


class GenericCsvParser:
    parser_id = "generic_csv"

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
                        "A linha não corresponde ao mapeamento CSV aprovado.",
                    )
                )
                continue

            values = values_by_column(row, profile.columns)
            mapping = spec.mapping
            issues = []
            try:
                transaction_date = parse_date(
                    values.get(mapping.transaction_date or "", ""),
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

            amount_text = values.get(mapping.amount or "", "")
            credit_text = values.get(mapping.credit or "", "")
            debit_text = values.get(mapping.debit or "", "")
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
                selected_amount = amount_text or credit_text or debit_text
                if selected_amount:
                    try:
                        amount_minor = parse_money(selected_amount)
                        if credit_text:
                            direction = TransactionDirection.INFLOW
                        elif debit_text:
                            direction = TransactionDirection.OUTFLOW
                        else:
                            direction_text = values.get(mapping.direction or "", "")
                            direction = direction_from_amount_text(
                                selected_amount
                            ) or direction_from_text(direction_text)
                    except ParserValueError:
                        issues.append(
                            extraction_issue(
                                DataQualityCode.INVALID_AMOUNT,
                                "amount_minor",
                                "O valor não pôde ser interpretado.",
                            )
                        )

            time_text = values.get(mapping.transaction_time or "", "")
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

            balance_minor = None
            balance_text = values.get(mapping.balance or "", "")
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

            description = values.get(mapping.description or "", "")
            payment_text = values.get(mapping.payment_method or "", "")
            payment_method, payment_instrument = infer_payment_context(
                payment_text or description
            )
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
                    external_id=values.get(mapping.external_id or "", "") or None,
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
