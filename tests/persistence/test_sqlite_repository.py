import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from finance_agent.application import ingest_and_persist, ingest_file
from finance_agent.ingestion.models import (
    DetectionStatus,
    IngestionOutcome,
    IngestionStatus,
    IngestionSummary,
)
from finance_agent.persistence import PersistenceStatus, SQLiteFinanceRepository
from finance_agent.persistence.repository import PersistenceError

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples" / "synthetic"
PICPAY = SAMPLES / "picpay_demo_jul_ago_2026.csv"
BRADESCO = SAMPLES / "bradesco_demo_jul_ago_2026.csv"


def test_migrations_are_versioned_and_idempotent(tmp_path: Path) -> None:
    repository = SQLiteFinanceRepository(tmp_path / "finance.db")

    first = repository.initialize()
    second = repository.initialize()

    assert first.schema_version == 2
    assert first.migrations_applied == 2
    assert second.schema_version == 2
    assert second.migrations_applied == 0


def test_picpay_is_persisted_and_reimport_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "finance.db"
    registry = tmp_path / "registry.json"

    first = ingest_and_persist(PICPAY, database_path=database, registry_path=registry)
    second = ingest_and_persist(PICPAY, database_path=database, registry_path=registry)

    assert first.persistence.status == PersistenceStatus.STORED
    assert first.persistence.transactions_inserted == 11
    assert first.persistence.database_summary.transactions == 11
    assert second.ingestion is None
    assert second.persistence.status == PersistenceStatus.ALREADY_IMPORTED
    assert second.persistence.database_summary.transactions == 11


def test_transaction_round_trip_preserves_exact_minor_units(tmp_path: Path) -> None:
    database = tmp_path / "finance.db"
    result = ingest_and_persist(
        BRADESCO,
        database_path=database,
        registry_path=tmp_path / "registry.json",
    )
    assert result.ingestion is not None
    original = next(item for item in result.ingestion.transactions if item.external_id == "84521")

    restored = SQLiteFinanceRepository(database).get_transaction(original.id)

    assert restored is not None
    assert restored.amount_minor == -8000
    assert restored.currency == "BRL"
    assert restored == original


def test_invalid_minimum_values_are_persisted_as_pending(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed_picpay.csv"
    malformed.write_text(
        "data,hora,tipo,origem / destino,valor,forma de pagamento\n"
        'data-invalida,08:00:00,Pagamento,LOJA DEMO,"R$ XX",Saldo PicPay\n',
        encoding="utf-8",
    )
    database = tmp_path / "finance.db"

    result = ingest_and_persist(
        malformed,
        database_path=database,
        registry_path=tmp_path / "registry.json",
    )
    pending = SQLiteFinanceRepository(database).list_open_pending()

    assert result.persistence.status == PersistenceStatus.STORED
    assert result.persistence.pending_inserted == 1
    assert result.persistence.database_summary.transactions == 0
    assert len(pending) == 1
    assert {issue.code.value for issue in pending[0].issues} == {
        "invalid_transaction_date",
        "invalid_amount",
    }


def test_cross_file_match_without_external_id_requires_review(tmp_path: Path) -> None:
    database = tmp_path / "finance.db"
    registry = tmp_path / "registry.json"
    first = ingest_and_persist(PICPAY, database_path=database, registry_path=registry)
    assert first.persistence.transactions_inserted == 11

    lines = PICPAY.read_text(encoding="utf-8").splitlines()
    overlapping = tmp_path / "overlapping_picpay.csv"
    overlapping.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    second = ingest_and_persist(
        overlapping,
        database_path=database,
        registry_path=registry,
    )

    assert second.persistence.transactions_inserted == 0
    assert second.persistence.cross_file_duplicates == 1
    assert second.persistence.database_summary.transactions == 11
    assert second.persistence.database_summary.duplicate_candidates == 1


def test_reliable_external_id_confirms_cross_file_duplicate(tmp_path: Path) -> None:
    database = tmp_path / "finance.db"
    registry = tmp_path / "registry.json"
    first = ingest_and_persist(BRADESCO, database_path=database, registry_path=registry)
    assert first.persistence.transactions_inserted == 11

    lines = BRADESCO.read_text(encoding="utf-8").splitlines()
    overlapping = tmp_path / "overlapping_bradesco.csv"
    overlapping.write_text("\n".join([*lines[:3], lines[5]]) + "\n", encoding="utf-8")
    second = ingest_and_persist(
        overlapping,
        database_path=database,
        registry_path=registry,
    )

    assert second.persistence.transactions_inserted == 0
    assert second.persistence.cross_file_duplicates == 1
    with sqlite3.connect(database) as connection:
        strategy, status = connection.execute(
            "SELECT detection_strategy, status FROM duplicate_candidates"
        ).fetchone()
    assert strategy == "external_id"
    assert status == "confirmed_duplicate"


def test_write_failure_rolls_back_every_financial_row(tmp_path: Path) -> None:
    database = tmp_path / "finance.db"
    repository = SQLiteFinanceRepository(database)
    repository.initialize()

    malformed = tmp_path / "malformed_picpay.csv"
    malformed.write_text(
        "data,hora,tipo,origem / destino,valor,forma de pagamento\n"
        'data-invalida,08:00:00,Pagamento,LOJA DEMO,"R$ XX",Saldo PicPay\n',
        encoding="utf-8",
    )
    valid = ingest_file(PICPAY, registry_path=tmp_path / "registry.json")
    invalid = ingest_file(malformed, registry_path=tmp_path / "registry.json")
    import_id = uuid4()
    transaction = valid.transactions[0].model_copy(update={"import_id": import_id})
    pending = invalid.pending[0].model_copy(update={"import_id": import_id})
    mixed = IngestionOutcome(
        summary=IngestionSummary(
            import_id=import_id,
            status=IngestionStatus.COMPLETED_WITH_ISSUES,
            detection_status=DetectionStatus.KNOWN,
            format_id="atomicity_test",
            institution="Synthetic",
            records_read=2,
            transactions_created=1,
            pending_created=1,
        ),
        transactions=[transaction],
        pending=[pending],
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER force_pending_failure
            BEFORE INSERT ON pending_transactions
            BEGIN
                SELECT RAISE(ABORT, 'forced failure');
            END
            """
        )

    with pytest.raises(PersistenceError):
        repository.persist(mixed, "f" * 64)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM pending_transactions").fetchone()[0] == 0


def test_blocked_ingestion_records_attempt_without_financial_rows(tmp_path: Path) -> None:
    result = ingest_and_persist(
        tmp_path / "missing.csv",
        database_path=tmp_path / "finance.db",
        registry_path=tmp_path / "registry.json",
    )

    assert result.persistence.status == PersistenceStatus.NOT_STORED
    assert result.persistence.database_summary.import_attempts == 1
    assert result.persistence.database_summary.transactions == 0


def test_pending_query_rejects_unbounded_limits(tmp_path: Path) -> None:
    repository = SQLiteFinanceRepository(tmp_path / "finance.db")

    with pytest.raises(ValueError):
        repository.list_open_pending(limit=0)
    with pytest.raises(ValueError):
        repository.list_open_pending(limit=1001)
