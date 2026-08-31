"""Repositório SQLite com gravação atômica e deduplicação conservadora."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from finance_agent.domain.models import PendingTransaction, Transaction
from finance_agent.ingestion.models import IngestionOutcome
from finance_agent.persistence.migrations import apply_migrations
from finance_agent.persistence.models import (
    DatabaseSummary,
    MigrationSummary,
    PersistenceStatus,
    PersistenceSummary,
)

DEFAULT_DATABASE_PATH = Path("private_data/finance_agent.db")


class PersistenceError(RuntimeError):
    """A persistência falhou sem expor detalhes ou dados do lançamento."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256(parts: list[str]) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _reliable_external_id(value: str | None) -> bool:
    if value is None:
        return False
    cleaned = value.strip()
    return bool(cleaned) and not (cleaned.isdigit() and set(cleaned) == {"0"})


def _strong_dedup_key(transaction: Transaction) -> str | None:
    if not _reliable_external_id(transaction.external_id):
        return None
    return _sha256(
        [
            transaction.source_institution.casefold(),
            transaction.source_account_ref or "",
            transaction.external_id or "",
            transaction.transaction_date.isoformat(),
            str(transaction.amount_minor),
            transaction.currency,
        ]
    )


def _semantic_fingerprint(transaction: Transaction) -> str:
    return _sha256(
        [
            transaction.source_institution.casefold(),
            transaction.transaction_date.isoformat(),
            str(transaction.amount_minor),
            transaction.currency,
            transaction.description_normalized,
        ]
    )


class SQLiteFinanceRepository:
    """Único ponto que conhece tabelas e comandos específicos do SQLite."""

    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> MigrationSummary:
        try:
            with closing(self._connect()) as connection:
                return apply_migrations(connection)
        except (OSError, sqlite3.Error) as exc:
            raise PersistenceError("storage_initialize_failed") from exc

    def summary(self) -> DatabaseSummary:
        self.initialize()
        try:
            with closing(self._connect()) as connection:
                schema_version = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                    ).fetchone()[0]
                )
                queries = {
                    "import_attempts": "SELECT COUNT(*) FROM import_runs",
                    "completed_imports": (
                        "SELECT COUNT(*) FROM import_runs WHERE persistence_status = 'stored'"
                    ),
                    "transactions": "SELECT COUNT(*) FROM transactions",
                    "open_pending": (
                        "SELECT COUNT(*) FROM pending_transactions WHERE status = 'open'"
                    ),
                    "duplicate_candidates": (
                        "SELECT COUNT(*) FROM duplicate_candidates WHERE status IN "
                        "('open_review', 'confirmed_duplicate')"
                    ),
                }
                values = {
                    name: int(connection.execute(query).fetchone()[0])
                    for name, query in queries.items()
                }
        except (OSError, sqlite3.Error) as exc:
            raise PersistenceError("storage_read_failed") from exc
        return DatabaseSummary(schema_version=schema_version, **values)

    def find_completed_import(self, source_file_hash: str) -> sqlite3.Row | None:
        self.initialize()
        with closing(self._connect()) as connection:
            return connection.execute(
                """
                SELECT * FROM import_runs
                WHERE source_file_hash = ? AND persistence_status = 'stored'
                """,
                (source_file_hash,),
            ).fetchone()

    def record_unstored_attempt(
        self,
        outcome: IngestionOutcome,
        source_file_hash: str | None,
        *,
        persistence_status: PersistenceStatus = PersistenceStatus.NOT_STORED,
        error_code: str | None = None,
    ) -> PersistenceSummary:
        self.initialize()
        summary = outcome.summary
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO import_runs (
                    id, source_file_hash, source_institution, format_id,
                    detection_status, ingestion_status, persistence_status,
                    records_read, transactions_created, pending_created,
                    duplicates_in_file, duplicates_in_database, records_rejected,
                    issue_counts_json, error_code, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                """,
                (
                    str(summary.import_id),
                    source_file_hash,
                    summary.institution,
                    summary.format_id,
                    summary.detection_status.value,
                    summary.status.value,
                    persistence_status.value,
                    summary.records_read,
                    summary.transactions_created,
                    summary.pending_created,
                    summary.duplicates_found,
                    summary.records_rejected,
                    _json(summary.issue_counts),
                    error_code,
                    _utc_now(),
                    _utc_now(),
                ),
            )
        return PersistenceSummary(
            import_id=summary.import_id,
            status=persistence_status,
            database_summary=self.summary(),
            error_code=error_code,
        )

    def persist(self, outcome: IngestionOutcome, source_file_hash: str) -> PersistenceSummary:
        """Grava lote completo ou reverte tudo; nunca deixa linhas parciais."""

        self.initialize()
        previous = self.find_completed_import(source_file_hash)
        if previous is not None:
            return PersistenceSummary(
                import_id=UUID(previous["id"]),
                status=PersistenceStatus.ALREADY_IMPORTED,
                database_summary=self.summary(),
            )

        inserted = 0
        pending_inserted = 0
        cross_file_duplicates = 0
        summary = outcome.summary
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO import_runs (
                        id, source_file_hash, source_institution, format_id,
                        detection_status, ingestion_status, persistence_status,
                        records_read, transactions_created, pending_created,
                        duplicates_in_file, duplicates_in_database, records_rejected,
                        issue_counts_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'stored', ?, 0, 0, ?, 0, ?, ?, ?)
                    """,
                    (
                        str(summary.import_id),
                        source_file_hash,
                        summary.institution,
                        summary.format_id,
                        summary.detection_status.value,
                        summary.status.value,
                        summary.records_read,
                        summary.duplicates_found,
                        summary.records_rejected,
                        _json(summary.issue_counts),
                        _utc_now(),
                    ),
                )

                for transaction in outcome.transactions:
                    duplicate = self._find_duplicate(connection, transaction)
                    if duplicate is not None:
                        existing_id, strategy, duplicate_status, fingerprint = duplicate
                        self._insert_duplicate(
                            connection,
                            transaction,
                            existing_id,
                            strategy,
                            duplicate_status,
                            fingerprint,
                        )
                        cross_file_duplicates += 1
                        continue
                    self._insert_transaction(connection, transaction)
                    inserted += 1

                for pending in outcome.pending:
                    self._insert_pending(connection, pending)
                    pending_inserted += 1

                connection.execute(
                    """
                    UPDATE import_runs
                    SET transactions_created = ?, pending_created = ?,
                        duplicates_in_database = ?, completed_at = ?
                    WHERE id = ?
                    """,
                    (
                        inserted,
                        pending_inserted,
                        cross_file_duplicates,
                        _utc_now(),
                        str(summary.import_id),
                    ),
                )
        except sqlite3.Error as exc:
            raise PersistenceError("storage_write_failed") from exc

        return PersistenceSummary(
            import_id=summary.import_id,
            status=PersistenceStatus.STORED,
            transactions_inserted=inserted,
            pending_inserted=pending_inserted,
            cross_file_duplicates=cross_file_duplicates,
            database_summary=self.summary(),
        )

    def _find_duplicate(
        self,
        connection: sqlite3.Connection,
        transaction: Transaction,
    ) -> tuple[str, str, str, str] | None:
        strong_key = _strong_dedup_key(transaction)
        semantic = _semantic_fingerprint(transaction)
        if strong_key is not None:
            row = connection.execute(
                "SELECT id FROM transactions WHERE strong_dedup_key = ?",
                (strong_key,),
            ).fetchone()
            if row is not None:
                return row["id"], "external_id", "confirmed_duplicate", strong_key
            return None

        row = connection.execute(
            "SELECT id FROM transactions WHERE semantic_fingerprint = ? LIMIT 1",
            (semantic,),
        ).fetchone()
        if row is None:
            return None
        return row["id"], "semantic_fingerprint", "open_review", semantic

    def _insert_transaction(
        self,
        connection: sqlite3.Connection,
        transaction: Transaction,
    ) -> None:
        connection.execute(
            """
            INSERT INTO transactions (
                id, import_id, transaction_date, transaction_time, amount_minor,
                currency, description_raw, description_normalized,
                source_institution, source_record_hash, external_id,
                strong_dedup_key, semantic_fingerprint, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(transaction.id),
                str(transaction.import_id),
                transaction.transaction_date.isoformat(),
                transaction.transaction_time.isoformat()
                if transaction.transaction_time is not None
                else None,
                transaction.amount_minor,
                transaction.currency,
                transaction.description_raw,
                transaction.description_normalized,
                transaction.source_institution,
                transaction.source_record_hash,
                transaction.external_id,
                _strong_dedup_key(transaction),
                _semantic_fingerprint(transaction),
                transaction.model_dump_json(),
                _utc_now(),
            ),
        )

    def _insert_pending(
        self,
        connection: sqlite3.Connection,
        pending: PendingTransaction,
    ) -> None:
        connection.execute(
            """
            INSERT INTO pending_transactions (
                id, import_id, status, reason_codes_json, candidate_json,
                payload_json, created_at, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(pending.id),
                str(pending.import_id),
                pending.status.value,
                _json([issue.code.value for issue in pending.issues]),
                pending.candidate.model_dump_json(),
                pending.model_dump_json(),
                pending.created_at.isoformat(),
                pending.resolved_at.isoformat() if pending.resolved_at else None,
            ),
        )

    def _insert_duplicate(
        self,
        connection: sqlite3.Connection,
        transaction: Transaction,
        existing_transaction_id: str,
        strategy: str,
        status: str,
        fingerprint: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO duplicate_candidates (
                import_id, existing_transaction_id, candidate_transaction_id,
                detection_strategy, status, fingerprint,
                candidate_payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(transaction.import_id),
                existing_transaction_id,
                str(transaction.id),
                strategy,
                status,
                fingerprint,
                transaction.model_dump_json(),
                _utc_now(),
            ),
        )

    def get_transaction(self, transaction_id: UUID) -> Transaction | None:
        self.initialize()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload_json FROM transactions WHERE id = ?",
                (str(transaction_id),),
            ).fetchone()
        return Transaction.model_validate_json(row["payload_json"]) if row else None

    def list_open_pending(self, *, limit: int = 100) -> list[PendingTransaction]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit deve estar entre 1 e 1000")
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM pending_transactions
                WHERE status = 'open' ORDER BY created_at LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [PendingTransaction.model_validate_json(row["payload_json"]) for row in rows]
