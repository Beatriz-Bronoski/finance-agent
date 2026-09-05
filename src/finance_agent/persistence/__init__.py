"""Persistência local, versionada e independente dos parsers bancários."""

from finance_agent.persistence.classification_repository import (
    ClassificationPersistenceError,
    SQLiteClassificationRepository,
)
from finance_agent.persistence.models import (
    DatabaseSummary,
    MigrationSummary,
    PersistedIngestionResult,
    PersistenceStatus,
    PersistenceSummary,
)
from finance_agent.persistence.repository import SQLiteFinanceRepository

__all__ = [
    "ClassificationPersistenceError",
    "DatabaseSummary",
    "MigrationSummary",
    "PersistedIngestionResult",
    "PersistenceStatus",
    "PersistenceSummary",
    "SQLiteClassificationRepository",
    "SQLiteFinanceRepository",
]
