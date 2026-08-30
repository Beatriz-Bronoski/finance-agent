"""Utilitários determinísticos compartilhados pelos parsers."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, time
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from finance_agent.domain.enums import (
    DataQualityCode,
    IssueSeverity,
    PaymentInstrument,
    PaymentMethod,
    TransactionDirection,
)
from finance_agent.domain.models import DataQualityIssue, SourceLocation
from finance_agent.domain.money import MoneyConversionError, decimal_to_minor
from finance_agent.domain.quality import normalize_description
from finance_agent.ingestion.models import (
    CsvSchemaProfile,
    IngestionIssueCode,
    ParseDiagnostic,
)


class ParserValueError(ValueError):
    pass


def read_csv_rows(path: Path, profile: CsvSchemaProfile) -> list[tuple[int, list[str]]]:
    text = path.read_text(encoding=profile.encoding)
    reader = csv.reader(io.StringIO(text), delimiter=profile.delimiter)
    rows: list[tuple[int, list[str]]] = []
    for row in reader:
        row_number = reader.line_num
        if row_number <= profile.header_row_number:
            continue
        if any(cell.strip() for cell in row):
            rows.append((row_number, row))
    return rows


def file_identity(path: Path) -> tuple[str, UUID]:
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return file_hash, uuid5(NAMESPACE_URL, file_hash)


def record_hash(row: list[str]) -> str:
    payload = json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def source_location(file_id: UUID, row_number: int) -> SourceLocation:
    return SourceLocation(file_id=file_id, row_number=row_number)


def parse_date(value: str, date_order: str | None = None) -> date:
    cleaned = value.strip()
    formats_by_order = {
        "ymd": ("%Y-%m-%d", "%Y/%m/%d"),
        "dmy": ("%d/%m/%Y", "%d-%m-%Y"),
        "mdy": ("%m/%d/%Y", "%m-%d-%Y"),
    }
    if date_order is not None:
        date_formats = formats_by_order.get(date_order, ())
    elif re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", cleaned):
        date_formats = formats_by_order["ymd"]
    else:
        parts = re.split(r"[-/]", cleaned)
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            date_formats = ()
        else:
            first, second = int(parts[0]), int(parts[1])
            if first > 12 and second <= 12:
                date_formats = formats_by_order["dmy"]
            elif second > 12 and first <= 12:
                date_formats = formats_by_order["mdy"]
            else:
                date_formats = ()

    for date_format in date_formats:
        try:
            return datetime.strptime(cleaned, date_format).date()
        except ValueError:
            continue
    raise ParserValueError("data inválida")


def parse_time(value: str) -> time | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    for time_format in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(cleaned, time_format).time()
        except ValueError:
            continue
    raise ParserValueError("hora inválida")


def parse_money(value: str) -> int:
    raw = value.strip().replace("−", "-").replace("–", "-")
    if not raw:
        raise ParserValueError("valor vazio")

    parenthesized = raw.startswith("(") and raw.endswith(")")
    sign = -1 if parenthesized or raw.lstrip().startswith("-") else 1
    cleaned = re.sub(r"[^0-9,.]", "", raw)
    if not cleaned or not any(char.isdigit() for char in cleaned):
        raise ParserValueError("valor inválido")

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        decimals = len(cleaned) - cleaned.rfind(",") - 1
        cleaned = cleaned.replace(",", ".") if decimals in {1, 2} else cleaned.replace(",", "")
    elif "." in cleaned:
        decimals = len(cleaned) - cleaned.rfind(".") - 1
        if decimals not in {1, 2}:
            cleaned = cleaned.replace(".", "")

    try:
        return sign * decimal_to_minor(cleaned)
    except MoneyConversionError as exc:
        raise ParserValueError("valor inválido") from exc


def direction_from_amount_text(value: str) -> TransactionDirection | None:
    cleaned = value.strip().replace("−", "-").replace("–", "-")
    if cleaned.startswith("-") or (cleaned.startswith("(") and cleaned.endswith(")")):
        return TransactionDirection.OUTFLOW
    if cleaned.startswith("+"):
        return TransactionDirection.INFLOW
    return None


INFLOW_TERMS = {
    "CREDIT",
    "CREDITO",
    "DEPOSIT",
    "DEPOSITO",
    "ENTRADA",
    "ESTORNO",
    "RECEIVED",
    "RECEBIDO",
    "RENDIMENTO",
}
OUTFLOW_TERMS = {
    "COMPRA",
    "DEBITO",
    "DEBIT",
    "ENVIADO",
    "PAGAMENTO",
    "PAYMENT",
    "PURCHASE",
    "SAIDA",
    "SAQUE",
    "WITHDRAWAL",
}


def direction_from_text(value: str) -> TransactionDirection | None:
    tokens = set(normalize_description(value).split())
    has_inflow = bool(tokens & INFLOW_TERMS)
    has_outflow = bool(tokens & OUTFLOW_TERMS)
    if has_inflow == has_outflow:
        return None
    return TransactionDirection.INFLOW if has_inflow else TransactionDirection.OUTFLOW


def infer_payment_context(
    value: str,
) -> tuple[PaymentMethod | None, PaymentInstrument | None]:
    normalized = normalize_description(value)
    if "CARTAO" in normalized:
        return PaymentMethod.CREDIT_CARD, PaymentInstrument.CREDIT_CARD
    if "PIX" in normalized:
        return PaymentMethod.PIX, PaymentInstrument.BANK_ACCOUNT
    if "BOLETO" in normalized:
        return PaymentMethod.BOLETO, PaymentInstrument.BANK_ACCOUNT
    if "SAQUE" in normalized or "DINHEIRO" in normalized:
        return PaymentMethod.CASH, PaymentInstrument.CASH
    if "SALDO PICPAY" in normalized:
        return PaymentMethod.DIGITAL_WALLET, PaymentInstrument.WALLET
    if "TRANSFERENCIA" in normalized:
        return PaymentMethod.BANK_TRANSFER, PaymentInstrument.BANK_ACCOUNT
    return None, None


def extraction_issue(code: DataQualityCode, field: str, message: str) -> DataQualityIssue:
    return DataQualityIssue(
        code=code,
        field=field,
        severity=IssueSeverity.BLOCKING,
        message=message,
    )


def optional_value_warning(row_number: int, message: str) -> ParseDiagnostic:
    return ParseDiagnostic(
        code=IngestionIssueCode.INVALID_ROW,
        severity=IssueSeverity.WARNING,
        row_number=row_number,
        message=message,
    )


def values_by_column(
    row: list[str],
    columns: tuple[str, ...],
) -> dict[str, str]:
    return {
        column: row[index].strip() if index < len(row) else ""
        for index, column in enumerate(columns)
        if column
    }
    "RECEIVED",
