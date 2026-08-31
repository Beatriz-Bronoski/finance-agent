"""Perfil de CSV, sugestão de mapeamento e detecção de mudanças estruturais."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

from finance_agent.domain.enums import IssueSeverity
from finance_agent.domain.quality import normalize_description
from finance_agent.ingestion.models import (
    ColumnMapping,
    CsvSchemaProfile,
    DetectionCandidate,
    DetectionResult,
    DetectionStatus,
    FormatSpec,
    IngestionIssueCode,
    MappingSuggestion,
    SchemaChange,
    SchemaDriftReport,
)

MAX_CSV_BYTES = 10 * 1024 * 1024
SUPPORTED_DELIMITERS = ",;\t|"


class SchemaProfileError(ValueError):
    def __init__(self, code: IngestionIssueCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def normalize_column_name(value: str) -> str:
    return normalize_description(value).lower()


def _decode_csv(content: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" not in text:
            return text, encoding
    raise SchemaProfileError(
        IngestionIssueCode.UNREADABLE_FILE,
        "O arquivo não possui uma codificação textual suportada.",
    )


def _detect_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=SUPPORTED_DELIMITERS).delimiter
    except csv.Error:
        lines = [line for line in sample.splitlines() if line.strip()][:20]
        scores = {
            delimiter: sum(line.count(delimiter) for line in lines)
            for delimiter in SUPPORTED_DELIMITERS
        }
        delimiter, score = max(scores.items(), key=lambda item: item[1])
        if score == 0:
            raise SchemaProfileError(
                IngestionIssueCode.UNKNOWN_FORMAT,
                "Não foi possível identificar a estrutura de colunas.",
            )
        return delimiter


HEADER_CONCEPTS = {
    "data",
    "date",
    "data movimento",
    "data transacao",
    "hora",
    "time",
    "tipo",
    "historico",
    "descricao",
    "detalhes",
    "origem destino",
    "valor",
    "montante",
    "amount",
    "credito",
    "debito",
    "saldo",
    "balance",
    "docto",
    "documento",
    "forma de pagamento",
    "natureza",
}


def _header_score(row: list[str]) -> int:
    normalized = {normalize_column_name(cell) for cell in row if cell.strip()}
    score = 0
    for column in normalized:
        if column in HEADER_CONCEPTS:
            score += 2
        elif any(concept in column for concept in HEADER_CONCEPTS if len(concept) >= 4):
            score += 1
    return score


class SchemaProfiler:
    def __init__(self, max_file_bytes: int = MAX_CSV_BYTES) -> None:
        self.max_file_bytes = max_file_bytes

    def profile(self, path: Path) -> CsvSchemaProfile:
        if not path.is_file():
            raise SchemaProfileError(
                IngestionIssueCode.UNREADABLE_FILE,
                "O arquivo informado não existe ou não pode ser lido.",
            )
        if path.stat().st_size > self.max_file_bytes:
            raise SchemaProfileError(
                IngestionIssueCode.FILE_TOO_LARGE,
                "O arquivo ultrapassa o limite seguro para ingestão local.",
            )

        content = path.read_bytes()
        text, encoding = _decode_csv(content)
        delimiter = _detect_delimiter(text[:32768])
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        if not rows:
            raise SchemaProfileError(
                IngestionIssueCode.UNKNOWN_FORMAT,
                "O arquivo não contém linhas para análise.",
            )

        scored = [(_header_score(row), index, row) for index, row in enumerate(rows[:30])]
        best_score, header_index, header = max(scored, key=lambda item: (item[0], -item[1]))
        if best_score == 0:
            candidates = [
                (index, row)
                for index, row in enumerate(rows[:30])
                if sum(bool(cell.strip()) for cell in row) >= 2
            ]
            if not candidates:
                raise SchemaProfileError(
                    IngestionIssueCode.MISSING_MINIMUM_COLUMN,
                    "Não foi possível localizar um cabeçalho tabular.",
                )
            header_index, header = candidates[0]

        columns = tuple(normalize_column_name(cell) for cell in header)
        if not any(columns):
            raise SchemaProfileError(
                IngestionIssueCode.MISSING_MINIMUM_COLUMN,
                "O cabeçalho não contém nomes de colunas utilizáveis.",
            )

        data_rows = [row for row in rows[header_index + 1 :] if any(cell.strip() for cell in row)]
        irregular = sum(len(row) != len(header) for row in data_rows)
        signature_payload = json.dumps(
            {"delimiter": delimiter, "columns": columns},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        signature = hashlib.sha256(signature_payload).hexdigest()
        return CsvSchemaProfile(
            delimiter=delimiter,
            encoding=encoding,
            header_row_number=header_index + 1,
            columns=columns,
            row_count=len(data_rows),
            irregular_row_count=irregular,
            signature=signature,
            source_file_hash=hashlib.sha256(content).hexdigest(),
        )


FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "transaction_date": (
        "data",
        "date",
        "data transacao",
        "data da transacao",
        "data movimento",
        "transaction date",
    ),
    "description": (
        "descricao",
        "description",
        "historico",
        "origem destino",
        "estabelecimento",
        "merchant",
        "memo",
        "detalhes",
        "details",
    ),
    "amount": ("valor", "valor r", "amount", "montante", "transaction amount"),
    "direction": ("tipo", "natureza", "direction", "movimento"),
    "transaction_time": ("hora", "time", "horario"),
    "credit": ("credito", "credit", "entrada"),
    "debit": ("debito", "debit", "saida"),
    "balance": ("saldo", "balance"),
    "external_id": ("docto", "documento", "id", "transaction id"),
    "payment_method": ("forma de pagamento", "payment method", "metodo pagamento"),
}


def _column_match_score(column: str, synonyms: tuple[str, ...]) -> float:
    if column in synonyms:
        return 1.0
    column_tokens = set(column.split())
    best = 0.0
    for synonym in synonyms:
        synonym_tokens = set(synonym.split())
        if not synonym_tokens:
            continue
        overlap = len(column_tokens & synonym_tokens) / len(column_tokens | synonym_tokens)
        if synonym in column or column in synonym:
            overlap = max(overlap, 0.8)
        best = max(best, overlap)
    return best


def suggest_column_mapping(profile: CsvSchemaProfile) -> MappingSuggestion:
    selected: dict[str, str | None] = {}
    field_scores: dict[str, float] = {}
    used_columns: set[str] = set()

    for field, synonyms in FIELD_SYNONYMS.items():
        scored = sorted(
            (
                (_column_match_score(column, synonyms), column)
                for column in profile.columns
                if column and column not in used_columns
            ),
            reverse=True,
        )
        score, column = scored[0] if scored else (0.0, "")
        if score >= 0.6:
            selected[field] = column
            field_scores[field] = score
            used_columns.add(column)
        else:
            selected[field] = None
            field_scores[field] = 0.0

    mapping = ColumnMapping(**selected)
    missing: list[str] = []
    if mapping.transaction_date is None:
        missing.append("transaction_date")
    if mapping.description is None:
        missing.append("description")
    if mapping.amount is None and mapping.credit is None and mapping.debit is None:
        missing.append("amount")

    mandatory_scores = [
        field_scores["transaction_date"],
        field_scores["description"],
        max(field_scores["amount"], field_scores["credit"], field_scores["debit"]),
    ]
    confidence = sum(mandatory_scores) / len(mandatory_scores)
    return MappingSuggestion(
        mapping=mapping,
        confidence=round(confidence, 4),
        missing_fields=tuple(missing),
    )


def builtin_format_specs() -> tuple[FormatSpec, ...]:
    return (
        FormatSpec(
            format_id="picpay_csv_v1",
            institution="PicPay",
            parser_id="picpay_csv",
            currency="BRL",
            date_order="ymd",
            delimiter=",",
            expected_columns=(
                "data",
                "hora",
                "tipo",
                "origem destino",
                "valor",
                "forma de pagamento",
            ),
            required_columns=frozenset({"data", "origem destino", "valor"}),
            mapping=ColumnMapping(
                transaction_date="data",
                transaction_time="hora",
                direction="tipo",
                description="origem destino",
                amount="valor",
                payment_method="forma de pagamento",
            ),
        ),
        FormatSpec(
            format_id="bradesco_csv_v1",
            institution="Bradesco",
            parser_id="bradesco_csv",
            currency="BRL",
            date_order="dmy",
            delimiter=";",
            expected_columns=("data", "historico", "docto", "credito", "debito", "saldo"),
            required_columns=frozenset({"data", "historico"}),
            required_any_groups=(frozenset({"credito", "debito"}),),
            mapping=ColumnMapping(
                transaction_date="data",
                description="historico",
                credit="credito",
                debit="debito",
                balance="saldo",
                external_id="docto",
            ),
        ),
    )


class FormatDetector:
    def __init__(self, learned_specs: tuple[FormatSpec, ...] = (), threshold: float = 0.72) -> None:
        self.specs = (*builtin_format_specs(), *learned_specs)
        self.threshold = threshold

    @staticmethod
    def _score(profile: CsvSchemaProfile, spec: FormatSpec) -> float:
        expected = set(spec.expected_columns)
        present = set(profile.columns)
        coverage = len(expected & present) / len(expected) if expected else 0.0
        delimiter_score = 1.0 if profile.delimiter == spec.delimiter else 0.0
        return round(coverage * 0.85 + delimiter_score * 0.15, 4)

    def detect(self, profile: CsvSchemaProfile) -> DetectionResult:
        scored_specs = sorted(
            ((self._score(profile, spec), spec) for spec in self.specs),
            key=lambda item: item[0],
            reverse=True,
        )
        candidates = [
            DetectionCandidate(
                format_id=spec.format_id,
                institution=spec.institution,
                confidence=score,
            )
            for score, spec in scored_specs[:3]
        ]

        if scored_specs and scored_specs[0][0] >= self.threshold:
            top_score, top_spec = scored_specs[0]
            if len(scored_specs) > 1:
                second_score, _second_spec = scored_specs[1]
                if second_score >= self.threshold and abs(top_score - second_score) <= 0.03:
                    return DetectionResult(
                        status=DetectionStatus.AMBIGUOUS,
                        candidates=candidates,
                    )
            return DetectionResult(
                status=DetectionStatus.LEARNED if top_spec.learned else DetectionStatus.KNOWN,
                candidates=candidates,
                selected_spec=top_spec,
            )

        suggestion = suggest_column_mapping(profile)
        if suggestion.mapping.is_complete:
            return DetectionResult(
                status=DetectionStatus.GENERIC,
                candidates=candidates,
                suggested_mapping=suggestion,
            )
        return DetectionResult(
            status=DetectionStatus.UNKNOWN,
            candidates=candidates,
            suggested_mapping=suggestion,
        )


class SchemaDriftDetector:
    def compare(self, profile: CsvSchemaProfile, spec: FormatSpec) -> SchemaDriftReport:
        present = set(profile.columns)
        expected = set(spec.expected_columns)
        changes: list[SchemaChange] = []

        missing = expected - present
        if missing:
            blocking = bool(missing & spec.required_columns)
            for group in spec.required_any_groups:
                if not (group & present):
                    blocking = True
            changes.append(
                SchemaChange(
                    code=IngestionIssueCode.MISSING_COLUMN,
                    severity=IssueSeverity.BLOCKING if blocking else IssueSeverity.WARNING,
                    fields=tuple(sorted(missing)),
                    message="Uma ou mais colunas conhecidas não foram encontradas.",
                )
            )

        for group in spec.required_any_groups:
            if not (group & present) and not missing.intersection(group):
                changes.append(
                    SchemaChange(
                        code=IngestionIssueCode.MISSING_MINIMUM_COLUMN,
                        severity=IssueSeverity.BLOCKING,
                        fields=tuple(sorted(group)),
                        message="Nenhuma coluna compatível com o valor foi encontrada.",
                    )
                )

        unexpected = present - expected
        if unexpected:
            changes.append(
                SchemaChange(
                    code=IngestionIssueCode.UNEXPECTED_COLUMN,
                    severity=IssueSeverity.WARNING,
                    fields=tuple(sorted(unexpected)),
                    message="O arquivo possui colunas que não existiam no formato conhecido.",
                )
            )

        if profile.delimiter != spec.delimiter:
            changes.append(
                SchemaChange(
                    code=IngestionIssueCode.DELIMITER_CHANGED,
                    severity=IssueSeverity.WARNING,
                    message="O delimitador difere do formato conhecido.",
                )
            )

        common_actual = tuple(column for column in profile.columns if column in expected)
        common_expected = tuple(column for column in spec.expected_columns if column in present)
        if common_actual != common_expected:
            changes.append(
                SchemaChange(
                    code=IngestionIssueCode.COLUMN_ORDER_CHANGED,
                    severity=IssueSeverity.WARNING,
                    message="A ordem das colunas mudou, mas o mapeamento por nome será usado.",
                )
            )

        if profile.irregular_row_count:
            changes.append(
                SchemaChange(
                    code=IngestionIssueCode.IRREGULAR_ROW_WIDTH,
                    severity=IssueSeverity.WARNING,
                    message="Existem linhas com quantidade de colunas diferente do cabeçalho.",
                )
            )

        return SchemaDriftReport(format_id=spec.format_id, changes=changes)
