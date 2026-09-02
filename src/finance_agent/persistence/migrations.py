"""Migrações SQLite pequenas, explícitas e testáveis sem ferramenta externa."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from finance_agent.persistence.models import MigrationSummary

Migration = tuple[int, str, Callable[[sqlite3.Connection], None]]


def _migration_001_initial_schema(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE import_runs (
            id TEXT PRIMARY KEY,
            source_file_hash TEXT,
            source_institution TEXT,
            format_id TEXT,
            detection_status TEXT NOT NULL,
            ingestion_status TEXT NOT NULL,
            persistence_status TEXT NOT NULL,
            records_read INTEGER NOT NULL DEFAULT 0 CHECK (records_read >= 0),
            transactions_created INTEGER NOT NULL DEFAULT 0 CHECK (transactions_created >= 0),
            pending_created INTEGER NOT NULL DEFAULT 0 CHECK (pending_created >= 0),
            duplicates_in_file INTEGER NOT NULL DEFAULT 0 CHECK (duplicates_in_file >= 0),
            duplicates_in_database INTEGER NOT NULL DEFAULT 0
                CHECK (duplicates_in_database >= 0),
            records_rejected INTEGER NOT NULL DEFAULT 0 CHECK (records_rejected >= 0),
            issue_counts_json TEXT NOT NULL DEFAULT '{}',
            error_code TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
        """,
        """
        CREATE UNIQUE INDEX uq_completed_import_file_hash
        ON import_runs(source_file_hash)
        WHERE persistence_status = 'stored' AND source_file_hash IS NOT NULL
        """,
        """
        CREATE TABLE transactions (
            id TEXT PRIMARY KEY,
            import_id TEXT NOT NULL REFERENCES import_runs(id) ON DELETE RESTRICT,
            transaction_date TEXT NOT NULL,
            transaction_time TEXT,
            amount_minor INTEGER NOT NULL CHECK (amount_minor <> 0),
            currency TEXT NOT NULL CHECK (length(currency) = 3),
            description_raw TEXT NOT NULL CHECK (length(description_raw) > 0),
            description_normalized TEXT NOT NULL CHECK (length(description_normalized) > 0),
            source_institution TEXT NOT NULL,
            source_record_hash TEXT NOT NULL CHECK (length(source_record_hash) = 64),
            external_id TEXT,
            strong_dedup_key TEXT UNIQUE,
            semantic_fingerprint TEXT NOT NULL CHECK (length(semantic_fingerprint) = 64),
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        ("CREATE INDEX ix_transactions_semantic_fingerprint ON transactions(semantic_fingerprint)"),
        "CREATE INDEX ix_transactions_date ON transactions(transaction_date)",
        """
        CREATE TABLE pending_transactions (
            id TEXT PRIMARY KEY,
            import_id TEXT NOT NULL REFERENCES import_runs(id) ON DELETE RESTRICT,
            status TEXT NOT NULL,
            reason_codes_json TEXT NOT NULL,
            candidate_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )
        """,
        "CREATE INDEX ix_pending_status ON pending_transactions(status)",
        """
        CREATE TABLE duplicate_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id TEXT NOT NULL REFERENCES import_runs(id) ON DELETE RESTRICT,
            existing_transaction_id TEXT NOT NULL
                REFERENCES transactions(id) ON DELETE RESTRICT,
            candidate_transaction_id TEXT NOT NULL,
            detection_strategy TEXT NOT NULL,
            status TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            candidate_payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX ix_duplicate_candidates_status ON duplicate_candidates(status)",
    )
    for statement in statements:
        connection.execute(statement)


def _migration_002_classification_schema(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL CHECK (length(name) > 0),
            normalized_name TEXT NOT NULL UNIQUE CHECK (length(normalized_name) > 0),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE classification_rules (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL CHECK (length(name) > 0),
            priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 1000),
            nature TEXT NOT NULL CHECK (
                nature IN ('despesa', 'receita', 'transferencia_interna', 'estorno')
            ),
            category_id TEXT REFERENCES categories(id) ON DELETE RESTRICT,
            description_exact TEXT,
            merchant_exact TEXT,
            counterparty_exact TEXT,
            source_institution TEXT,
            card_alias TEXT,
            rule_fingerprint TEXT NOT NULL UNIQUE CHECK (length(rule_fingerprint) = 64),
            is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
            created_by_user INTEGER NOT NULL DEFAULT 1
                CHECK (created_by_user IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (
                description_exact IS NOT NULL OR merchant_exact IS NOT NULL
                OR counterparty_exact IS NOT NULL OR source_institution IS NOT NULL
                OR card_alias IS NOT NULL
            )
        )
        """,
        "CREATE INDEX ix_classification_rules_priority ON classification_rules(priority DESC)",
        """
        CREATE TABLE classification_decisions (
            id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE RESTRICT,
            nature TEXT NOT NULL CHECK (
                nature IN ('despesa', 'receita', 'transferencia_interna', 'estorno')
            ),
            category_id TEXT REFERENCES categories(id) ON DELETE RESTRICT,
            source TEXT NOT NULL CHECK (source IN ('rule', 'user')),
            rule_id TEXT REFERENCES classification_rules(id) ON DELETE SET NULL,
            matched_rule_ids_json TEXT NOT NULL DEFAULT '[]',
            reason_code TEXT NOT NULL,
            is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
            created_at TEXT NOT NULL,
            superseded_at TEXT
        )
        """,
        """
        CREATE UNIQUE INDEX uq_current_classification_decision
        ON classification_decisions(transaction_id) WHERE is_current = 1
        """,
        "CREATE INDEX ix_classification_decisions_transaction ON classification_decisions(transaction_id)",
        """
        CREATE TABLE classification_reviews (
            id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE RESTRICT,
            status TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
            reason_code TEXT NOT NULL,
            candidate_rule_ids_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )
        """,
        """
        CREATE UNIQUE INDEX uq_open_classification_review
        ON classification_reviews(transaction_id) WHERE status = 'open'
        """,
        "CREATE INDEX ix_classification_reviews_status ON classification_reviews(status)",
        """
        CREATE TABLE classification_corrections (
            id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE RESTRICT,
            previous_decision_id TEXT
                REFERENCES classification_decisions(id) ON DELETE RESTRICT,
            new_decision_id TEXT NOT NULL
                REFERENCES classification_decisions(id) ON DELETE RESTRICT,
            remembered_rule_id TEXT REFERENCES classification_rules(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX ix_classification_corrections_transaction ON classification_corrections(transaction_id)",
    )
    for statement in statements:
        connection.execute(statement)


MIGRATIONS: tuple[Migration, ...] = (
    (1, "initial_persistence_schema", _migration_001_initial_schema),
    (2, "classification_schema", _migration_002_classification_schema),
)
CURRENT_SCHEMA_VERSION = MIGRATIONS[-1][0]


def apply_migrations(connection: sqlite3.Connection) -> MigrationSummary:
    """Aplica apenas versões ainda ausentes, cada uma em uma transação."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied = {int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")}
    applied_now = 0
    for version, name, migration in MIGRATIONS:
        if version in applied:
            continue
        with connection:
            migration(connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, datetime.now(UTC).isoformat()),
            )
        applied_now += 1

    current = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()[0]
    return MigrationSummary(schema_version=int(current), migrations_applied=applied_now)
