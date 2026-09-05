"""Motor determinístico: maior prioridade vence; empate divergente exige revisão."""

from __future__ import annotations

from finance_agent.classification.models import (
    ClassificationProposal,
    ClassificationRule,
    ClassificationRunSummary,
    ClassificationStatus,
    ReviewReason,
)
from finance_agent.domain.models import ClassificationContext
from finance_agent.persistence.classification_repository import SQLiteClassificationRepository


def classify_context(
    context: ClassificationContext,
    rules: list[ClassificationRule],
) -> ClassificationProposal:
    """Produz uma decisão explicável sem gravar ou alterar dados."""

    matching = [rule for rule in rules if rule.is_enabled and rule.matches(context)]
    if not matching:
        return ClassificationProposal(
            status=ClassificationStatus.PENDING_REVIEW,
            review_reason=ReviewReason.NO_MATCHING_RULE,
        )

    highest_priority = max(rule.priority for rule in matching)
    winners = sorted(
        (rule for rule in matching if rule.priority == highest_priority),
        key=lambda rule: str(rule.id),
    )
    outcomes = {(rule.nature, rule.category_id) for rule in winners}
    winner_ids = [rule.id for rule in winners]
    if len(outcomes) > 1:
        return ClassificationProposal(
            status=ClassificationStatus.PENDING_REVIEW,
            matched_rule_ids=winner_ids,
            review_reason=ReviewReason.PRIORITY_CONFLICT,
        )

    selected = winners[0]
    return ClassificationProposal(
        status=ClassificationStatus.CLASSIFIED,
        nature=selected.nature,
        category_id=selected.category_id,
        winning_rule_id=selected.id,
        matched_rule_ids=winner_ids,
    )


def classify_pending_transactions(
    repository: SQLiteClassificationRepository,
    *,
    limit: int = 500,
) -> ClassificationRunSummary:
    """Classifica apenas itens sem decisão atual; nunca reescreve histórico confirmado."""

    transactions, skipped = repository.list_transactions_for_classification(limit=limit)
    rules = repository.list_rules(enabled_only=True)
    classified = 0
    pending = 0
    for transaction in transactions:
        proposal = classify_context(ClassificationContext.from_transaction(transaction), rules)
        if proposal.status == ClassificationStatus.CLASSIFIED:
            repository.record_rule_decision(transaction.id, proposal)
            classified += 1
            continue
        repository.open_review(
            transaction.id,
            proposal.review_reason or ReviewReason.NO_MATCHING_RULE,
            proposal.matched_rule_ids,
        )
        pending += 1

    return ClassificationRunSummary(
        examined=len(transactions),
        classified=classified,
        pending_review=pending,
        skipped_with_decision=skipped,
    )
