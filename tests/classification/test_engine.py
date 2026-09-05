import sqlite3
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from finance_agent.application import ingest_and_persist
from finance_agent.classification.engine import classify_context, classify_pending_transactions
from finance_agent.classification.models import (
    ClassificationRule,
    ClassificationStatus,
    DecisionSource,
    ReviewReason,
    TransactionNature,
)
from finance_agent.domain.models import ClassificationContext, Transaction
from finance_agent.persistence.classification_repository import SQLiteClassificationRepository
from finance_agent.persistence.migrations import MIGRATIONS

ROOT = Path(__file__).resolve().parents[2]
PICPAY = ROOT / "samples" / "synthetic" / "picpay_demo_jul_ago_2026.csv"


def _persist_picpay(tmp_path: Path) -> SQLiteClassificationRepository:
    database = tmp_path / "finance.db"
    ingest_and_persist(
        PICPAY,
        database_path=database,
        registry_path=tmp_path / "registry.json",
    )
    return SQLiteClassificationRepository(database)


def _market_transaction(repository: SQLiteClassificationRepository) -> Transaction:
    transactions, _ = repository.list_transactions_for_classification()
    return next(
        item for item in transactions if item.description_normalized == "MERCADO FICTICIO AURORA"
    )


def test_rule_model_requires_category_for_expense_and_income() -> None:
    with pytest.raises(ValueError, match="categoria"):
        ClassificationRule(
            name="Inválida",
            nature=TransactionNature.EXPENSE,
            description_exact="LOJA TESTE",
        )

    transfer = ClassificationRule(
        name="Transferência",
        nature=TransactionNature.INTERNAL_TRANSFER,
        description_exact="CONTA PROPRIA",
    )
    refund = ClassificationRule(
        name="Estorno",
        nature=TransactionNature.REFUND,
        description_exact="ESTORNO TESTE",
    )

    assert transfer.category_id is None
    assert refund.category_id is None


def test_highest_priority_wins_and_lower_rule_cannot_override() -> None:
    context = ClassificationContext(
        transaction_date=date(2026, 8, 1),
        amount_minor=-1000,
        currency="BRL",
        description="LOJA TESTE",
        source_institution="Banco Teste",
    )
    lower_category = uuid4()
    higher_category = uuid4()
    lower = ClassificationRule(
        name="Baixa",
        priority=400,
        nature=TransactionNature.EXPENSE,
        category_id=lower_category,
        description_exact="loja téste",
    )
    higher = ClassificationRule(
        name="Alta",
        priority=800,
        nature=TransactionNature.EXPENSE,
        category_id=higher_category,
        description_exact="LOJA TESTE",
    )

    result = classify_context(context, [lower, higher])

    assert result.status == ClassificationStatus.CLASSIFIED
    assert result.category_id == higher_category
    assert result.winning_rule_id == higher.id


def test_equal_priority_with_same_output_is_audited_without_conflict() -> None:
    context = ClassificationContext(
        transaction_date=date(2026, 8, 1),
        amount_minor=-1000,
        currency="BRL",
        description="LOJA TESTE",
        source_institution="Banco Teste",
    )
    category_id = uuid4()
    rules = [
        ClassificationRule(
            name=name,
            priority=800,
            nature=TransactionNature.EXPENSE,
            category_id=category_id,
            description_exact="LOJA TESTE",
        )
        for name in ("Regra A", "Regra B")
    ]

    result = classify_context(context, rules)

    assert result.status == ClassificationStatus.CLASSIFIED
    assert result.category_id == category_id
    assert set(result.matched_rule_ids) == {rule.id for rule in rules}


def test_optional_rule_criteria_must_all_match_when_present() -> None:
    context = ClassificationContext(
        transaction_date=date(2026, 8, 1),
        amount_minor=-1000,
        currency="BRL",
        description="PIX CONTA PROPRIA",
        source_institution="Banco Teste",
        card_alias="Cartão principal",
        counterparty_name="Pessoa Teste",
        merchant_name="Carteira Teste",
    )
    rule = ClassificationRule(
        name="Transferência própria",
        nature=TransactionNature.INTERNAL_TRANSFER,
        description_exact="pix conta própria",
        source_institution="banco teste",
        card_alias="cartao principal",
        counterparty_exact="pessoa teste",
        merchant_exact="carteira teste",
    )

    matching = classify_context(context, [rule])
    different_card = classify_context(
        context.model_copy(update={"card_alias": "Outro cartão"}),
        [rule],
    )

    assert matching.status == ClassificationStatus.CLASSIFIED
    assert matching.nature == TransactionNature.INTERNAL_TRANSFER
    assert different_card.status == ClassificationStatus.PENDING_REVIEW


def test_equal_priority_with_different_outputs_requires_review() -> None:
    context = ClassificationContext(
        transaction_date=date(2026, 8, 1),
        amount_minor=-1000,
        currency="BRL",
        description="LOJA TESTE",
        source_institution="Banco Teste",
    )
    rules = [
        ClassificationRule(
            name=name,
            priority=800,
            nature=TransactionNature.EXPENSE,
            category_id=uuid4(),
            description_exact="LOJA TESTE",
        )
        for name in ("Opção A", "Opção B")
    ]

    result = classify_context(context, rules)

    assert result.status == ClassificationStatus.PENDING_REVIEW
    assert result.review_reason == ReviewReason.PRIORITY_CONFLICT
    assert set(result.matched_rule_ids) == {rule.id for rule in rules}


def test_no_rule_creates_one_review_without_duplicate_rows(tmp_path: Path) -> None:
    repository = _persist_picpay(tmp_path)

    first = classify_pending_transactions(repository)
    second = classify_pending_transactions(repository)
    reviews = repository.list_open_reviews()

    assert first.examined == 11
    assert first.pending_review == 11
    assert second.examined == 11
    assert len(reviews) == 11
    assert {review.reason for review in reviews} == {ReviewReason.NO_MATCHING_RULE}


def test_user_correction_can_be_remembered_for_future_transaction(tmp_path: Path) -> None:
    repository = _persist_picpay(tmp_path)
    category = repository.create_category("Alimentação")
    transaction = _market_transaction(repository)
    classify_pending_transactions(repository)

    correction = repository.correct_classification(
        transaction.id,
        nature=TransactionNature.EXPENSE,
        category_name="alimentacao",
        remember=True,
    )

    assert correction.decision.source == DecisionSource.USER
    assert correction.decision.category_id == category.id
    assert correction.remembered_rule_id is not None
    assert all(item.transaction_id != transaction.id for item in repository.list_open_reviews())

    future = tmp_path / "future_picpay.csv"
    future.write_text(
        "data,hora,tipo,origem / destino,valor,forma de pagamento\n"
        '2026-09-01,08:00:00,Pagamento,MERCADO FICTICIO AURORA,"−R$ 20,00",Saldo PicPay\n',
        encoding="utf-8",
    )
    ingest_and_persist(
        future,
        database_path=repository.database_path,
        registry_path=tmp_path / "registry.json",
    )
    result = classify_pending_transactions(repository)
    database_summary = repository.classification_summary()

    assert result.classified == 1
    assert database_summary.classified_transactions == 2
    assert database_summary.corrections == 1


def test_existing_decision_is_not_silently_reclassified(tmp_path: Path) -> None:
    repository = _persist_picpay(tmp_path)
    first_category = repository.create_category("Alimentação")
    second_category = repository.create_category("Lazer")
    transaction = _market_transaction(repository)
    repository.correct_classification(
        transaction.id,
        nature=TransactionNature.EXPENSE,
        category_name=first_category.name,
    )
    repository.create_rule(
        ClassificationRule(
            name="Nova regra mais forte",
            priority=1000,
            nature=TransactionNature.EXPENSE,
            category_id=second_category.id,
            description_exact=transaction.description_normalized,
        )
    )

    result = classify_pending_transactions(repository)
    current = repository.get_current_decision(transaction.id)

    assert result.skipped_with_decision == 1
    assert current is not None
    assert current.category_id == first_category.id
    assert current.source == DecisionSource.USER


def test_disabled_rule_and_inactive_category_are_not_applied(tmp_path: Path) -> None:
    repository = _persist_picpay(tmp_path)
    category = repository.create_category("Alimentação")
    transaction = _market_transaction(repository)
    rule = repository.create_rule(
        ClassificationRule(
            name="Mercado",
            nature=TransactionNature.EXPENSE,
            category_id=category.id,
            description_exact=transaction.description_normalized,
        )
    )

    assert repository.set_rule_enabled(rule.id, enabled=False)
    result = classify_pending_transactions(repository)
    assert result.classified == 0

    assert repository.set_rule_enabled(rule.id, enabled=True)
    assert repository.set_category_active(category.id, active=False)
    result = classify_pending_transactions(repository)
    assert result.classified == 0
    assert repository.classification_summary().enabled_rules == 0


def test_existing_version_one_database_is_migrated_without_recreation(tmp_path: Path) -> None:
    database = tmp_path / "version_one.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        MIGRATIONS[0][2](connection)
        connection.execute(
            """
            INSERT INTO schema_migrations(version, name, applied_at)
            VALUES (1, 'initial_persistence_schema', '2026-08-30T00:00:00+00:00')
            """
        )

    migration = SQLiteClassificationRepository(database).initialize()
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert migration.schema_version == 2
    assert migration.migrations_applied == 1
    assert {"transactions", "categories", "classification_decisions"} <= tables


def test_correction_preserves_auditable_decision_history(tmp_path: Path) -> None:
    repository = _persist_picpay(tmp_path)
    food = repository.create_category("Alimentação")
    leisure = repository.create_category("Lazer")
    transaction = _market_transaction(repository)
    repository.correct_classification(
        transaction.id,
        nature=TransactionNature.EXPENSE,
        category_name=food.name,
    )
    repository.correct_classification(
        transaction.id,
        nature=TransactionNature.EXPENSE,
        category_name=leisure.name,
    )

    history = repository.list_decision_history(transaction.id)

    assert len(history) == 2
    assert history[0].is_current is False
    assert history[1].is_current is True
    assert history[1].category_id == leisure.id


def test_internal_transfer_needs_no_category_and_can_be_marked_for_review(tmp_path: Path) -> None:
    repository = _persist_picpay(tmp_path)
    transactions, _ = repository.list_transactions_for_classification()
    transaction = next(
        item for item in transactions if item.description_normalized == "PESSOA TESTE BETA"
    )

    correction = repository.correct_classification(
        transaction.id,
        nature=TransactionNature.INTERNAL_TRANSFER,
    )
    review = repository.mark_for_review(transaction.id)
    current = repository.get_current_decision(transaction.id)

    assert correction.decision.category_id is None
    assert review.reason == ReviewReason.USER_REQUESTED
    assert current is not None
    assert current.nature == TransactionNature.INTERNAL_TRANSFER


def test_repository_conflict_records_only_rule_ids_not_financial_values(tmp_path: Path) -> None:
    repository = _persist_picpay(tmp_path)
    transaction = _market_transaction(repository)
    categories = [repository.create_category(name) for name in ("Alimentação", "Lazer")]
    for category in categories:
        repository.create_rule(
            ClassificationRule(
                name=f"Regra {category.name}",
                priority=900,
                nature=TransactionNature.EXPENSE,
                category_id=category.id,
                description_exact=transaction.description_normalized,
            )
        )

    classify_pending_transactions(repository)
    review = next(
        item for item in repository.list_open_reviews() if item.transaction_id == transaction.id
    )

    assert review.reason == ReviewReason.PRIORITY_CONFLICT
    assert len(review.candidate_rule_ids) == 2
