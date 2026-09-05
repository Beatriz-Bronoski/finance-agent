"""Persistência SQLite da classificação, separada do motor de regras."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from finance_agent.classification.models import (
    Category,
    ClassificationDatabaseSummary,
    ClassificationDecision,
    ClassificationProposal,
    ClassificationReview,
    ClassificationRule,
    ClassificationStatus,
    CorrectionResult,
    DecisionSource,
    ReviewReason,
    TransactionNature,
)
from finance_agent.domain.models import ClassificationContext, Transaction
from finance_agent.domain.quality import normalize_description
from finance_agent.persistence.repository import (
    DEFAULT_DATABASE_PATH,
    PersistenceError,
    SQLiteFinanceRepository,
)


class ClassificationPersistenceError(PersistenceError):
    """Uma operação de classificação falhou sem expor dados financeiros."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _rule_fingerprint(rule: ClassificationRule) -> str:
    payload = _json(
        {
            "priority": rule.priority,
            "nature": rule.nature.value,
            "category_id": str(rule.category_id) if rule.category_id else None,
            "description_exact": rule.description_exact,
            "merchant_exact": rule.merchant_exact,
            "counterparty_exact": rule.counterparty_exact,
            "source_institution": rule.source_institution,
            "card_alias": rule.card_alias,
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_rule(rule: ClassificationRule) -> ClassificationRule:
    fields = {
        field: normalize_description(value) if value is not None else None
        for field, value in {
            "description_exact": rule.description_exact,
            "merchant_exact": rule.merchant_exact,
            "counterparty_exact": rule.counterparty_exact,
            "source_institution": rule.source_institution,
            "card_alias": rule.card_alias,
        }.items()
    }
    return rule.model_copy(update=fields)


class SQLiteClassificationRepository(SQLiteFinanceRepository):
    """Operações atômicas de categorias, regras, decisões e correções."""

    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        super().__init__(database_path)

    def create_category(self, name: str) -> Category:
        normalized_name = normalize_description(name)
        if not normalized_name:
            raise ValueError("category_name_required")
        category = Category(name=name, normalized_name=normalized_name)
        self.initialize()
        try:
            with closing(self._connect()) as connection, connection:
                existing = connection.execute(
                    "SELECT * FROM categories WHERE normalized_name = ?",
                    (normalized_name,),
                ).fetchone()
                if existing is not None:
                    return self._category_from_row(existing)
                now = _utc_now()
                connection.execute(
                    """
                    INSERT INTO categories(
                        id, name, normalized_name, is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, 1, ?, ?)
                    """,
                    (str(category.id), category.name, category.normalized_name, now, now),
                )
        except sqlite3.Error as exc:
            raise ClassificationPersistenceError("classification_category_write_failed") from exc
        return category

    def list_categories(self, *, active_only: bool = False) -> list[Category]:
        self.initialize()
        query = "SELECT * FROM categories"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY normalized_name"
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(query).fetchall()
        except sqlite3.Error as exc:
            raise ClassificationPersistenceError("classification_category_read_failed") from exc
        return [self._category_from_row(row) for row in rows]

    def set_category_active(self, category_id: UUID, *, active: bool) -> bool:
        self.initialize()
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    "UPDATE categories SET is_active = ?, updated_at = ? WHERE id = ?",
                    (int(active), _utc_now(), str(category_id)),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise ClassificationPersistenceError("classification_category_update_failed") from exc

    def create_rule(self, rule: ClassificationRule) -> ClassificationRule:
        normalized = _normalize_rule(rule)
        self.initialize()
        try:
            with closing(self._connect()) as connection, connection:
                self._require_active_category(connection, normalized.category_id)
                return self._insert_or_get_rule(connection, normalized)
        except sqlite3.Error as exc:
            raise ClassificationPersistenceError("classification_rule_write_failed") from exc

    def list_rules(self, *, enabled_only: bool = False) -> list[ClassificationRule]:
        self.initialize()
        query = """
            SELECT r.* FROM classification_rules AS r
            LEFT JOIN categories AS c ON c.id = r.category_id
        """
        if enabled_only:
            query += """
                WHERE r.is_enabled = 1
                AND (r.category_id IS NULL OR c.is_active = 1)
            """
        query += " ORDER BY r.priority DESC, r.created_at, r.id"
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(query).fetchall()
        except sqlite3.Error as exc:
            raise ClassificationPersistenceError("classification_rule_read_failed") from exc
        return [self._rule_from_row(row) for row in rows]

    def set_rule_enabled(self, rule_id: UUID, *, enabled: bool) -> bool:
        self.initialize()
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    "UPDATE classification_rules SET is_enabled = ?, updated_at = ? WHERE id = ?",
                    (int(enabled), _utc_now(), str(rule_id)),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise ClassificationPersistenceError("classification_rule_update_failed") from exc

    def list_transactions_for_classification(
        self,
        *,
        limit: int = 500,
    ) -> tuple[list[Transaction], int]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit deve estar entre 1 e 1000")
        self.initialize()
        try:
            with closing(self._connect()) as connection:
                skipped = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM classification_decisions WHERE is_current = 1"
                    ).fetchone()[0]
                )
                rows = connection.execute(
                    """
                    SELECT t.payload_json FROM transactions AS t
                    WHERE NOT EXISTS (
                        SELECT 1 FROM classification_decisions AS d
                        WHERE d.transaction_id = t.id AND d.is_current = 1
                    )
                    ORDER BY t.transaction_date, t.created_at, t.id
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise ClassificationPersistenceError("classification_transaction_read_failed") from exc
        return [Transaction.model_validate_json(row["payload_json"]) for row in rows], skipped

    def record_rule_decision(
        self,
        transaction_id: UUID,
        proposal: ClassificationProposal,
    ) -> ClassificationDecision:
        if (
            proposal.status != ClassificationStatus.CLASSIFIED
            or proposal.nature is None
            or proposal.winning_rule_id is None
        ):
            raise ValueError("classified_proposal_required")
        self.initialize()
        try:
            with closing(self._connect()) as connection, connection:
                existing = self._current_decision_row(connection, transaction_id)
                if existing is not None:
                    return self._decision_from_row(existing)
                transaction = self._require_transaction(connection, transaction_id)
                rule_row = connection.execute(
                    """
                    SELECT r.* FROM classification_rules AS r
                    LEFT JOIN categories AS c ON c.id = r.category_id
                    WHERE r.id = ? AND r.is_enabled = 1
                    AND (r.category_id IS NULL OR c.is_active = 1)
                    """,
                    (str(proposal.winning_rule_id),),
                ).fetchone()
                if rule_row is None:
                    raise ValueError("winning_rule_not_available")
                winning_rule = self._rule_from_row(rule_row)
                if (
                    winning_rule.nature != proposal.nature
                    or winning_rule.category_id != proposal.category_id
                    or not winning_rule.matches(ClassificationContext.from_transaction(transaction))
                ):
                    raise ValueError("winning_rule_does_not_support_proposal")
                decision = ClassificationDecision(
                    transaction_id=transaction_id,
                    nature=proposal.nature,
                    category_id=proposal.category_id,
                    source=DecisionSource.RULE,
                    rule_id=proposal.winning_rule_id,
                    matched_rule_ids=proposal.matched_rule_ids,
                    reason_code="highest_priority_rule",
                )
                self._insert_decision(connection, decision)
                self._resolve_reviews(connection, transaction_id)
                return decision
        except sqlite3.Error as exc:
            raise ClassificationPersistenceError("classification_decision_write_failed") from exc

    def open_review(
        self,
        transaction_id: UUID,
        reason: ReviewReason,
        candidate_rule_ids: list[UUID] | None = None,
    ) -> ClassificationReview:
        self.initialize()
        candidates = sorted(candidate_rule_ids or [], key=str)
        try:
            with closing(self._connect()) as connection, connection:
                self._require_transaction(connection, transaction_id)
                existing = connection.execute(
                    """
                    SELECT * FROM classification_reviews
                    WHERE transaction_id = ? AND status = 'open'
                    """,
                    (str(transaction_id),),
                ).fetchone()
                if existing is not None:
                    connection.execute(
                        """
                        UPDATE classification_reviews
                        SET reason_code = ?, candidate_rule_ids_json = ?
                        WHERE id = ?
                        """,
                        (reason.value, _json([str(item) for item in candidates]), existing["id"]),
                    )
                    return ClassificationReview(
                        id=UUID(existing["id"]),
                        transaction_id=transaction_id,
                        reason=reason,
                        candidate_rule_ids=candidates,
                    )
                review = ClassificationReview(
                    transaction_id=transaction_id,
                    reason=reason,
                    candidate_rule_ids=candidates,
                )
                connection.execute(
                    """
                    INSERT INTO classification_reviews(
                        id, transaction_id, status, reason_code,
                        candidate_rule_ids_json, created_at
                    ) VALUES (?, ?, 'open', ?, ?, ?)
                    """,
                    (
                        str(review.id),
                        str(transaction_id),
                        reason.value,
                        _json([str(item) for item in candidates]),
                        _utc_now(),
                    ),
                )
                return review
        except sqlite3.Error as exc:
            raise ClassificationPersistenceError("classification_review_write_failed") from exc

    def list_open_reviews(self, *, limit: int = 100) -> list[ClassificationReview]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit deve estar entre 1 e 1000")
        self.initialize()
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM classification_reviews
                    WHERE status = 'open' ORDER BY created_at, id LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise ClassificationPersistenceError("classification_review_read_failed") from exc
        return [
            ClassificationReview(
                id=UUID(row["id"]),
                transaction_id=UUID(row["transaction_id"]),
                reason=ReviewReason(row["reason_code"]),
                candidate_rule_ids=[
                    UUID(item) for item in json.loads(row["candidate_rule_ids_json"])
                ],
            )
            for row in rows
        ]

    def mark_for_review(self, transaction_id: UUID) -> ClassificationReview:
        return self.open_review(transaction_id, ReviewReason.USER_REQUESTED)

    def correct_classification(
        self,
        transaction_id: UUID,
        *,
        nature: TransactionNature,
        category_name: str | None = None,
        remember: bool = False,
        rule_priority: int = 800,
    ) -> CorrectionResult:
        self.initialize()
        try:
            with closing(self._connect()) as connection, connection:
                transaction = self._require_transaction(connection, transaction_id)
                category = self._find_active_category(connection, category_name)
                if (
                    nature in {TransactionNature.EXPENSE, TransactionNature.INCOME}
                    and category is None
                ):
                    raise ValueError("expense_or_income_requires_active_category")

                remembered_rule_id: UUID | None = None
                if remember:
                    rule = ClassificationRule(
                        name="Regra lembrada pela usuária",
                        priority=rule_priority,
                        nature=nature,
                        category_id=category.id if category else None,
                        description_exact=transaction.description_normalized,
                        source_institution=transaction.source_institution,
                        created_by_user=True,
                    )
                    remembered = self._insert_or_get_rule(connection, _normalize_rule(rule))
                    remembered_rule_id = remembered.id

                previous = self._current_decision_row(connection, transaction_id)
                previous_id = UUID(previous["id"]) if previous is not None else None
                if previous is not None:
                    connection.execute(
                        """
                        UPDATE classification_decisions
                        SET is_current = 0, superseded_at = ? WHERE id = ?
                        """,
                        (_utc_now(), previous["id"]),
                    )

                decision = ClassificationDecision(
                    transaction_id=transaction_id,
                    nature=nature,
                    category_id=category.id if category else None,
                    category_name=category.name if category else None,
                    source=DecisionSource.USER,
                    reason_code="user_correction",
                )
                self._insert_decision(connection, decision)
                connection.execute(
                    """
                    INSERT INTO classification_corrections(
                        id, transaction_id, previous_decision_id, new_decision_id,
                        remembered_rule_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        str(transaction_id),
                        str(previous_id) if previous_id else None,
                        str(decision.id),
                        str(remembered_rule_id) if remembered_rule_id else None,
                        _utc_now(),
                    ),
                )
                self._resolve_reviews(connection, transaction_id)
                return CorrectionResult(
                    decision=decision,
                    remembered_rule_id=remembered_rule_id,
                )
        except sqlite3.Error as exc:
            raise ClassificationPersistenceError("classification_correction_write_failed") from exc

    def get_current_decision(self, transaction_id: UUID) -> ClassificationDecision | None:
        self.initialize()
        try:
            with closing(self._connect()) as connection:
                row = self._current_decision_row(connection, transaction_id)
        except sqlite3.Error as exc:
            raise ClassificationPersistenceError("classification_decision_read_failed") from exc
        return self._decision_from_row(row) if row is not None else None

    def list_decision_history(self, transaction_id: UUID) -> list[ClassificationDecision]:
        self.initialize()
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT d.*, c.name AS category_name
                    FROM classification_decisions AS d
                    LEFT JOIN categories AS c ON c.id = d.category_id
                    WHERE d.transaction_id = ? ORDER BY d.created_at, d.id
                    """,
                    (str(transaction_id),),
                ).fetchall()
        except sqlite3.Error as exc:
            raise ClassificationPersistenceError("classification_decision_read_failed") from exc
        return [self._decision_from_row(row) for row in rows]

    def classification_summary(self) -> ClassificationDatabaseSummary:
        self.initialize()
        queries = {
            "active_categories": "SELECT COUNT(*) FROM categories WHERE is_active = 1",
            "enabled_rules": (
                "SELECT COUNT(*) FROM classification_rules AS r "
                "LEFT JOIN categories AS c ON c.id = r.category_id "
                "WHERE r.is_enabled = 1 "
                "AND (r.category_id IS NULL OR c.is_active = 1)"
            ),
            "classified_transactions": (
                "SELECT COUNT(*) FROM classification_decisions WHERE is_current = 1"
            ),
            "open_reviews": "SELECT COUNT(*) FROM classification_reviews WHERE status = 'open'",
            "corrections": "SELECT COUNT(*) FROM classification_corrections",
        }
        try:
            with closing(self._connect()) as connection:
                values = {
                    name: int(connection.execute(query).fetchone()[0])
                    for name, query in queries.items()
                }
        except sqlite3.Error as exc:
            raise ClassificationPersistenceError("classification_summary_read_failed") from exc
        return ClassificationDatabaseSummary(**values)

    @staticmethod
    def _category_from_row(row: sqlite3.Row) -> Category:
        return Category(
            id=UUID(row["id"]),
            name=row["name"],
            normalized_name=row["normalized_name"],
            is_active=bool(row["is_active"]),
        )

    @staticmethod
    def _rule_from_row(row: sqlite3.Row) -> ClassificationRule:
        return ClassificationRule(
            id=UUID(row["id"]),
            name=row["name"],
            priority=int(row["priority"]),
            nature=TransactionNature(row["nature"]),
            category_id=UUID(row["category_id"]) if row["category_id"] else None,
            description_exact=row["description_exact"],
            merchant_exact=row["merchant_exact"],
            counterparty_exact=row["counterparty_exact"],
            source_institution=row["source_institution"],
            card_alias=row["card_alias"],
            is_enabled=bool(row["is_enabled"]),
            created_by_user=bool(row["created_by_user"]),
        )

    @staticmethod
    def _decision_from_row(row: sqlite3.Row) -> ClassificationDecision:
        keys = set(row.keys())
        return ClassificationDecision(
            id=UUID(row["id"]),
            transaction_id=UUID(row["transaction_id"]),
            nature=TransactionNature(row["nature"]),
            category_id=UUID(row["category_id"]) if row["category_id"] else None,
            category_name=row["category_name"] if "category_name" in keys else None,
            source=DecisionSource(row["source"]),
            rule_id=UUID(row["rule_id"]) if row["rule_id"] else None,
            matched_rule_ids=[UUID(item) for item in json.loads(row["matched_rule_ids_json"])],
            reason_code=row["reason_code"],
            is_current=bool(row["is_current"]),
        )

    @staticmethod
    def _require_transaction(
        connection: sqlite3.Connection,
        transaction_id: UUID,
    ) -> Transaction:
        row = connection.execute(
            "SELECT payload_json FROM transactions WHERE id = ?",
            (str(transaction_id),),
        ).fetchone()
        if row is None:
            raise ValueError("transaction_not_found")
        return Transaction.model_validate_json(row["payload_json"])

    @staticmethod
    def _find_active_category(
        connection: sqlite3.Connection,
        category_name: str | None,
    ) -> Category | None:
        if category_name is None:
            return None
        normalized = normalize_description(category_name)
        row = connection.execute(
            "SELECT * FROM categories WHERE normalized_name = ? AND is_active = 1",
            (normalized,),
        ).fetchone()
        if row is None:
            raise ValueError("active_category_not_found")
        return SQLiteClassificationRepository._category_from_row(row)

    @staticmethod
    def _require_active_category(
        connection: sqlite3.Connection,
        category_id: UUID | None,
    ) -> None:
        if category_id is None:
            return
        row = connection.execute(
            "SELECT 1 FROM categories WHERE id = ? AND is_active = 1",
            (str(category_id),),
        ).fetchone()
        if row is None:
            raise ValueError("active_category_not_found")

    @staticmethod
    def _current_decision_row(
        connection: sqlite3.Connection,
        transaction_id: UUID,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT d.*, c.name AS category_name
            FROM classification_decisions AS d
            LEFT JOIN categories AS c ON c.id = d.category_id
            WHERE d.transaction_id = ? AND d.is_current = 1
            """,
            (str(transaction_id),),
        ).fetchone()

    @staticmethod
    def _insert_decision(
        connection: sqlite3.Connection,
        decision: ClassificationDecision,
    ) -> None:
        connection.execute(
            """
            INSERT INTO classification_decisions(
                id, transaction_id, nature, category_id, source, rule_id,
                matched_rule_ids_json, reason_code, is_current, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(decision.id),
                str(decision.transaction_id),
                decision.nature.value,
                str(decision.category_id) if decision.category_id else None,
                decision.source.value,
                str(decision.rule_id) if decision.rule_id else None,
                _json([str(item) for item in decision.matched_rule_ids]),
                decision.reason_code,
                int(decision.is_current),
                _utc_now(),
            ),
        )

    @staticmethod
    def _resolve_reviews(connection: sqlite3.Connection, transaction_id: UUID) -> None:
        connection.execute(
            """
            UPDATE classification_reviews
            SET status = 'resolved', resolved_at = ?
            WHERE transaction_id = ? AND status = 'open'
            """,
            (_utc_now(), str(transaction_id)),
        )

    @staticmethod
    def _insert_or_get_rule(
        connection: sqlite3.Connection,
        rule: ClassificationRule,
    ) -> ClassificationRule:
        fingerprint = _rule_fingerprint(rule)
        existing = connection.execute(
            "SELECT * FROM classification_rules WHERE rule_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if existing is not None:
            if not existing["is_enabled"]:
                connection.execute(
                    """
                    UPDATE classification_rules
                    SET is_enabled = 1, updated_at = ? WHERE id = ?
                    """,
                    (_utc_now(), existing["id"]),
                )
                existing = connection.execute(
                    "SELECT * FROM classification_rules WHERE id = ?",
                    (existing["id"],),
                ).fetchone()
            return SQLiteClassificationRepository._rule_from_row(existing)

        now = _utc_now()
        connection.execute(
            """
            INSERT INTO classification_rules(
                id, name, priority, nature, category_id, description_exact,
                merchant_exact, counterparty_exact, source_institution,
                card_alias, rule_fingerprint, is_enabled, created_by_user,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(rule.id),
                rule.name,
                rule.priority,
                rule.nature.value,
                str(rule.category_id) if rule.category_id else None,
                rule.description_exact,
                rule.merchant_exact,
                rule.counterparty_exact,
                rule.source_institution,
                rule.card_alias,
                fingerprint,
                int(rule.is_enabled),
                int(rule.created_by_user),
                now,
                now,
            ),
        )
        return rule
