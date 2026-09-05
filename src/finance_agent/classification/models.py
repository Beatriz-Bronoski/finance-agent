"""Contratos da classificação determinística e auditável."""

from __future__ import annotations

from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from finance_agent.domain.models import ClassificationContext
from finance_agent.domain.quality import normalize_description


class ClassificationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TransactionNature(str, Enum):
    EXPENSE = "despesa"
    INCOME = "receita"
    INTERNAL_TRANSFER = "transferencia_interna"
    REFUND = "estorno"


class DecisionSource(str, Enum):
    RULE = "rule"
    USER = "user"


class ClassificationStatus(str, Enum):
    CLASSIFIED = "classified"
    PENDING_REVIEW = "pending_review"


class ReviewReason(str, Enum):
    NO_MATCHING_RULE = "no_matching_rule"
    PRIORITY_CONFLICT = "priority_conflict"
    USER_REQUESTED = "user_requested"


class Category(ClassificationModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=80)
    normalized_name: str = Field(min_length=1, max_length=80)
    is_active: bool = True


class ClassificationRule(ClassificationModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    priority: int = Field(default=800, ge=1, le=1000)
    nature: TransactionNature
    category_id: UUID | None = None
    description_exact: str | None = None
    merchant_exact: str | None = None
    counterparty_exact: str | None = None
    source_institution: str | None = None
    card_alias: str | None = None
    is_enabled: bool = True
    created_by_user: bool = True

    @field_validator(
        "description_exact",
        "merchant_exact",
        "counterparty_exact",
        "source_institution",
        "card_alias",
        mode="before",
    )
    @classmethod
    def normalize_match_criterion(cls, value: object) -> object:
        return normalize_description(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_match_criteria(self) -> ClassificationRule:
        criteria = (
            self.description_exact,
            self.merchant_exact,
            self.counterparty_exact,
            self.source_institution,
            self.card_alias,
        )
        if not any(criteria):
            raise ValueError("a regra precisa de ao menos um critério")
        if (
            self.nature in {TransactionNature.EXPENSE, TransactionNature.INCOME}
            and self.category_id is None
        ):
            raise ValueError("despesa e receita precisam de categoria")
        return self

    @property
    def criteria_count(self) -> int:
        return sum(
            value is not None
            for value in (
                self.description_exact,
                self.merchant_exact,
                self.counterparty_exact,
                self.source_institution,
                self.card_alias,
            )
        )

    def matches(self, context: ClassificationContext) -> bool:
        expected_and_actual = (
            (self.description_exact, context.description),
            (self.merchant_exact, context.merchant_name),
            (self.counterparty_exact, context.counterparty_name),
            (self.source_institution, context.source_institution),
            (self.card_alias, context.card_alias),
        )
        return all(
            expected is None or (actual is not None and expected == normalize_description(actual))
            for expected, actual in expected_and_actual
        )


class ClassificationDecision(ClassificationModel):
    id: UUID = Field(default_factory=uuid4)
    transaction_id: UUID
    nature: TransactionNature
    category_id: UUID | None = None
    category_name: str | None = None
    source: DecisionSource
    rule_id: UUID | None = None
    matched_rule_ids: list[UUID] = Field(default_factory=list)
    reason_code: str
    is_current: bool = True

    @model_validator(mode="after")
    def require_consistent_source_and_category(self) -> ClassificationDecision:
        if (
            self.nature in {TransactionNature.EXPENSE, TransactionNature.INCOME}
            and self.category_id is None
        ):
            raise ValueError("despesa e receita precisam de categoria")
        if self.source == DecisionSource.RULE and self.rule_id is None:
            raise ValueError("decisão de regra precisa identificar a regra")
        if self.source == DecisionSource.USER and self.rule_id is not None:
            raise ValueError("decisão manual não pode se apresentar como regra")
        return self


class ClassificationReview(ClassificationModel):
    id: UUID = Field(default_factory=uuid4)
    transaction_id: UUID
    reason: ReviewReason
    candidate_rule_ids: list[UUID] = Field(default_factory=list)


class ClassificationProposal(ClassificationModel):
    status: ClassificationStatus
    nature: TransactionNature | None = None
    category_id: UUID | None = None
    winning_rule_id: UUID | None = None
    matched_rule_ids: list[UUID] = Field(default_factory=list)
    review_reason: ReviewReason | None = None

    @model_validator(mode="after")
    def require_status_fields(self) -> ClassificationProposal:
        if self.status == ClassificationStatus.CLASSIFIED:
            if self.nature is None or self.winning_rule_id is None:
                raise ValueError("proposta classificada precisa de natureza e regra vencedora")
            if self.winning_rule_id not in self.matched_rule_ids:
                raise ValueError("regra vencedora precisa constar nas evidências")
            if self.review_reason is not None:
                raise ValueError("proposta classificada não pode exigir revisão")
        elif self.review_reason is None:
            raise ValueError("proposta pendente precisa de motivo de revisão")
        return self


class ClassificationRunSummary(ClassificationModel):
    examined: int = Field(ge=0)
    classified: int = Field(ge=0)
    pending_review: int = Field(ge=0)
    skipped_with_decision: int = Field(default=0, ge=0)


class ClassificationDatabaseSummary(ClassificationModel):
    active_categories: int = Field(ge=0)
    enabled_rules: int = Field(ge=0)
    classified_transactions: int = Field(ge=0)
    open_reviews: int = Field(ge=0)
    corrections: int = Field(ge=0)


class CorrectionResult(ClassificationModel):
    decision: ClassificationDecision
    remembered_rule_id: UUID | None = None
