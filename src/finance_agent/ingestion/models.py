"""Contratos seguros para detecção, parsing e relatórios de ingestão."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finance_agent.domain.enums import IssueSeverity
from finance_agent.domain.models import PendingTransaction, Transaction, TransactionCandidate


class IngestionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DetectionStatus(str, Enum):
    KNOWN = "known"
    LEARNED = "learned"
    GENERIC = "generic"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


class IngestionStatus(str, Enum):
    COMPLETED = "completed"
    COMPLETED_WITH_ISSUES = "completed_with_issues"
    BLOCKED = "blocked"
    FAILED = "failed"


class IngestionIssueCode(str, Enum):
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    FILE_TOO_LARGE = "file_too_large"
    FILE_CHANGED_DURING_READ = "file_changed_during_read"
    UNREADABLE_FILE = "unreadable_file"
    UNKNOWN_FORMAT = "unknown_format"
    AMBIGUOUS_FORMAT = "ambiguous_format"
    GENERIC_MAPPING_REQUIRES_APPROVAL = "generic_mapping_requires_approval"
    MISSING_CURRENCY = "missing_currency"
    MISSING_MINIMUM_COLUMN = "missing_minimum_column"
    MISSING_COLUMN = "missing_column"
    UNEXPECTED_COLUMN = "unexpected_column"
    DELIMITER_CHANGED = "delimiter_changed"
    COLUMN_ORDER_CHANGED = "column_order_changed"
    IRREGULAR_ROW_WIDTH = "irregular_row_width"
    INVALID_ROW = "invalid_row"
    NON_TRANSACTION_ROW = "non_transaction_row"
    DUPLICATE_RECORD = "duplicate_record"
    REGISTRY_INVALID = "registry_invalid"


class ColumnMapping(IngestionModel):
    transaction_date: str | None = None
    description: str | None = None
    amount: str | None = None
    direction: str | None = None
    transaction_time: str | None = None
    credit: str | None = None
    debit: str | None = None
    balance: str | None = None
    external_id: str | None = None
    payment_method: str | None = None

    @property
    def is_complete(self) -> bool:
        has_amount = self.amount is not None or self.credit is not None or self.debit is not None
        return self.transaction_date is not None and self.description is not None and has_amount


class CsvSchemaProfile(IngestionModel):
    delimiter: str = Field(min_length=1, max_length=1)
    encoding: str
    header_row_number: int = Field(ge=1)
    columns: tuple[str, ...]
    row_count: int = Field(ge=0)
    irregular_row_count: int = Field(ge=0)
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_file_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class FormatSpec(IngestionModel):
    format_id: str
    institution: str
    parser_id: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    date_order: Literal["ymd", "dmy", "mdy"] | None = None
    delimiter: str = Field(min_length=1, max_length=1)
    expected_columns: tuple[str, ...]
    required_columns: frozenset[str]
    required_any_groups: tuple[frozenset[str], ...] = ()
    mapping: ColumnMapping
    learned: bool = False


class MappingSuggestion(IngestionModel):
    mapping: ColumnMapping
    confidence: float = Field(ge=0, le=1)
    missing_fields: tuple[str, ...] = ()


class DetectionCandidate(IngestionModel):
    format_id: str
    institution: str
    confidence: float = Field(ge=0, le=1)


class DetectionResult(IngestionModel):
    status: DetectionStatus
    candidates: list[DetectionCandidate] = Field(default_factory=list)
    selected_spec: FormatSpec | None = None
    suggested_mapping: MappingSuggestion | None = None


class SchemaChange(IngestionModel):
    code: IngestionIssueCode
    severity: IssueSeverity
    fields: tuple[str, ...] = ()
    message: str


class SchemaDriftReport(IngestionModel):
    format_id: str
    changes: list[SchemaChange] = Field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.changes)

    @property
    def is_breaking(self) -> bool:
        return any(change.severity == IssueSeverity.BLOCKING for change in self.changes)


class ParseDiagnostic(IngestionModel):
    code: IngestionIssueCode
    severity: IssueSeverity
    message: str
    row_number: int | None = Field(default=None, ge=1)


class ParserResult(IngestionModel):
    records_read: int = Field(ge=0)
    candidates: list[TransactionCandidate] = Field(default_factory=list)
    rejected_count: int = Field(default=0, ge=0)
    diagnostics: list[ParseDiagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def records_must_balance(self) -> ParserResult:
        if len(self.candidates) + self.rejected_count != self.records_read:
            raise ValueError("contagens do parser não fecham com records_read")
        return self


class IngestionSummary(IngestionModel):
    import_id: UUID
    status: IngestionStatus
    detection_status: DetectionStatus
    format_id: str | None = None
    institution: str | None = None
    records_read: int = Field(default=0, ge=0)
    transactions_created: int = Field(default=0, ge=0)
    pending_created: int = Field(default=0, ge=0)
    duplicates_found: int = Field(default=0, ge=0)
    records_rejected: int = Field(default=0, ge=0)
    issue_counts: dict[str, int] = Field(default_factory=dict)
    drift: SchemaDriftReport | None = None

    @model_validator(mode="after")
    def completed_counts_must_balance(self) -> IngestionSummary:
        if self.status in {IngestionStatus.COMPLETED, IngestionStatus.COMPLETED_WITH_ISSUES}:
            accounted = (
                self.transactions_created
                + self.pending_created
                + self.duplicates_found
                + self.records_rejected
            )
            if accounted != self.records_read:
                raise ValueError("contagens da ingestão não fecham com records_read")
        return self


class IngestionOutcome(IngestionModel):
    summary: IngestionSummary
    transactions: list[Transaction] = Field(default_factory=list)
    pending: list[PendingTransaction] = Field(default_factory=list)
    suggested_mapping: MappingSuggestion | None = None


class RegistryDocument(IngestionModel):
    version: int = Field(default=1, ge=1)
    formats: list[FormatSpec] = Field(default_factory=list)


def json_ready(model: BaseModel) -> dict[str, Any]:
    """Serializa modelos para JSON sem depender de detalhes internos do Pydantic."""

    return model.model_dump(mode="json")
