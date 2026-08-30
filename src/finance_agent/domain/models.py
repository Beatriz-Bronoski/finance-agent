"""Modelos canônicos para dados de qualquer banco ou carteira."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from finance_agent.domain.enums import (
    ClassificationSource,
    DataQualityCode,
    ImportStatus,
    IssueSeverity,
    PaymentInstrument,
    PaymentMethod,
    PendingStatus,
    TransactionDirection,
)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceLocation(DomainModel):
    """Localiza o registro sem incluir nome de arquivo ou conteúdo sensível."""

    file_id: UUID
    row_number: int | None = Field(default=None, ge=1)
    page_number: int | None = Field(default=None, ge=1)
    block_number: int | None = Field(default=None, ge=1)


class DataQualityIssue(DomainModel):
    code: DataQualityCode
    field: str | None = None
    severity: IssueSeverity = IssueSeverity.BLOCKING
    message: str


class TransactionCandidate(DomainModel):
    """Saída tolerante de um parser antes da validação obrigatória."""

    transaction_date: date | None = None
    transaction_time: time | None = None
    amount_minor: int | None = None
    amount_direction: TransactionDirection | None = None
    description_raw: str | None = None

    source_institution: str = Field(min_length=1)
    source_location: SourceLocation
    source_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    external_id: str | None = None
    balance_minor: int | None = None
    payment_method: PaymentMethod | None = None
    payment_instrument: PaymentInstrument | None = None
    card_alias: str | None = None
    card_last_four: str | None = None
    source_account_ref: str | None = None
    counterparty_name: str | None = None
    merchant_name: str | None = None
    source_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    extraction_issues: list[DataQualityIssue] = Field(default_factory=list)

    @field_validator("card_last_four")
    @classmethod
    def validate_card_last_four(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != 4 or not value.isdigit()):
            raise ValueError("card_last_four deve conter exatamente quatro dígitos")
        return value


class Transaction(DomainModel):
    """Transação válida no formato canônico do projeto."""

    id: UUID = Field(default_factory=uuid4)
    import_id: UUID
    transaction_date: date
    transaction_time: time | None = None
    amount_minor: int
    currency: str = Field(default="BRL", pattern=r"^[A-Z]{3}$")
    description_raw: str = Field(min_length=1)
    description_normalized: str = Field(min_length=1)

    source_institution: str = Field(min_length=1)
    source_location: SourceLocation
    source_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    external_id: str | None = None
    balance_minor: int | None = None
    payment_method: PaymentMethod | None = None
    payment_instrument: PaymentInstrument | None = None
    card_alias: str | None = None
    card_last_four: str | None = None
    source_account_ref: str | None = None
    counterparty_name: str | None = None
    merchant_name: str | None = None
    source_metadata: dict[str, JsonValue] = Field(default_factory=dict)

    category: str | None = None
    classification_source: ClassificationSource | None = None
    classification_confidence: Decimal | None = Field(default=None, ge=0, le=1)

    @field_validator("amount_minor")
    @classmethod
    def reject_zero_amount(cls, value: int) -> int:
        if value == 0:
            raise ValueError("amount_minor não pode ser zero")
        return value

    @field_validator("card_last_four")
    @classmethod
    def validate_card_last_four(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != 4 or not value.isdigit()):
            raise ValueError("card_last_four deve conter exatamente quatro dígitos")
        return value


class PendingTransaction(DomainModel):
    """Candidato preservado para correção humana, sem descarte silencioso."""

    id: UUID = Field(default_factory=uuid4)
    import_id: UUID
    candidate: TransactionCandidate
    issues: list[DataQualityIssue] = Field(min_length=1)
    status: PendingStatus = PendingStatus.OPEN
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None

    @model_validator(mode="after")
    def require_blocking_issue(self) -> PendingTransaction:
        if not any(issue.severity == IssueSeverity.BLOCKING for issue in self.issues):
            raise ValueError("uma pendência precisa conter ao menos um bloqueio")
        if self.status == PendingStatus.OPEN and self.resolved_at is not None:
            raise ValueError("pendência aberta não pode possuir resolved_at")
        return self

    def mark_corrected(self) -> PendingTransaction:
        return self.model_copy(
            update={
                "status": PendingStatus.CORRECTED,
                "resolved_at": datetime.now(timezone.utc),
            }
        )


class CandidateCorrection(DomainModel):
    """Campos mínimos que uma interface (futuramente WhatsApp) pode corrigir."""

    transaction_date: date | None = None
    amount_minor: int | None = None
    amount_direction: TransactionDirection | None = None
    description_raw: str | None = None

    @model_validator(mode="after")
    def require_one_field(self) -> CandidateCorrection:
        supplied = self.model_dump(exclude_unset=True, exclude_none=True)
        if not supplied:
            raise ValueError("informe ao menos um campo não vazio para correção")
        return self


class CandidateValidationResult(DomainModel):
    transaction: Transaction | None = None
    pending: PendingTransaction | None = None
    issues: list[DataQualityIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_exactly_one_outcome(self) -> CandidateValidationResult:
        if (self.transaction is None) == (self.pending is None):
            raise ValueError("o resultado deve conter uma transação ou uma pendência")
        return self

    @property
    def is_valid(self) -> bool:
        return self.transaction is not None


class ClassificationContext(DomainModel):
    """Visão mínima e explícita permitida para regras/modelos de classificação."""

    transaction_date: date
    amount_minor: int
    description: str
    source_institution: str
    payment_method: PaymentMethod | None = None
    payment_instrument: PaymentInstrument | None = None
    card_alias: str | None = None
    counterparty_name: str | None = None
    merchant_name: str | None = None

    @classmethod
    def from_transaction(cls, transaction: Transaction) -> ClassificationContext:
        return cls(
            transaction_date=transaction.transaction_date,
            amount_minor=transaction.amount_minor,
            description=transaction.description_normalized,
            source_institution=transaction.source_institution,
            payment_method=transaction.payment_method,
            payment_instrument=transaction.payment_instrument,
            card_alias=transaction.card_alias,
            counterparty_name=transaction.counterparty_name,
            merchant_name=transaction.merchant_name,
        )


class ImportBatch(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    source_file_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_institution: str = Field(min_length=1)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ImportResult(DomainModel):
    import_id: UUID
    status: ImportStatus
    records_read: int = Field(ge=0)
    transactions_created: int = Field(ge=0)
    pending_created: int = Field(ge=0)
    records_rejected: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def counts_must_balance(self) -> ImportResult:
        accounted = self.transactions_created + self.pending_created + self.records_rejected
        if accounted != self.records_read:
            raise ValueError("contagens do lote não fecham com records_read")
        return self
