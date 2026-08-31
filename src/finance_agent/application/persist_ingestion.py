"""Caso de uso que liga a ingestão validada à persistência local."""

from __future__ import annotations

import hashlib
from pathlib import Path

from finance_agent.application.ingest_file import DEFAULT_REGISTRY_PATH, ingest_file
from finance_agent.ingestion.models import IngestionStatus
from finance_agent.persistence.models import (
    PersistedIngestionResult,
    PersistenceStatus,
    PersistenceSummary,
)
from finance_agent.persistence.repository import (
    DEFAULT_DATABASE_PATH,
    PersistenceError,
    SQLiteFinanceRepository,
)


def _file_hash(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def ingest_and_persist(
    path: str | Path,
    *,
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    approve_generic_as: str | None = None,
    generic_currency: str | None = None,
    generic_date_order: str | None = None,
) -> PersistedIngestionResult:
    """Executa a etapa 3 e persiste somente resultados concluídos."""

    source_path = Path(path)
    source_hash = _file_hash(source_path)
    repository = SQLiteFinanceRepository(database_path)
    repository.initialize()

    if source_hash is not None:
        existing = repository.find_completed_import(source_hash)
        if existing is not None:
            return PersistedIngestionResult(
                persistence=PersistenceSummary(
                    import_id=existing["id"],
                    status=PersistenceStatus.ALREADY_IMPORTED,
                    database_summary=repository.summary(),
                )
            )

    outcome = ingest_file(
        source_path,
        registry_path=registry_path,
        approve_generic_as=approve_generic_as,
        generic_currency=generic_currency,
        generic_date_order=generic_date_order,
    )
    completed = outcome.summary.status in {
        IngestionStatus.COMPLETED,
        IngestionStatus.COMPLETED_WITH_ISSUES,
    }
    final_hash = _file_hash(source_path)
    if not completed or source_hash is None or final_hash != source_hash:
        persistence = repository.record_unstored_attempt(outcome, source_hash)
        return PersistedIngestionResult(ingestion=outcome, persistence=persistence)

    try:
        persistence = repository.persist(outcome, source_hash)
    except PersistenceError:
        persistence = repository.record_unstored_attempt(
            outcome,
            source_hash,
            persistence_status=PersistenceStatus.FAILED,
            error_code="storage_write_failed",
        )
    return PersistedIngestionResult(ingestion=outcome, persistence=persistence)


def safe_persistence_lines(result: PersistedIngestionResult) -> list[str]:
    """Exibe apenas estado e contagens; nunca valores ou descrições financeiras."""

    persistence = result.persistence
    database = persistence.database_summary
    lines = [
        f"Persistência: {persistence.status.value}",
        f"Transações gravadas nesta execução: {persistence.transactions_inserted}",
        f"Pendências gravadas nesta execução: {persistence.pending_inserted}",
        f"Duplicidades entre arquivos: {persistence.cross_file_duplicates}",
        f"Total de importações concluídas: {database.completed_imports}",
        f"Total de transações no banco: {database.transactions}",
        f"Total de pendências abertas: {database.open_pending}",
        f"Candidatas a duplicidade: {database.duplicate_candidates}",
        f"Versão do banco: {database.schema_version}",
    ]
    if persistence.error_code is not None:
        lines.append(f"Erro seguro: {persistence.error_code}")
    return lines
