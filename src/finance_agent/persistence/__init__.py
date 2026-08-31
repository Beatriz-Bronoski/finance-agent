"""Persistência local, versionada e independente dos parsers bancários."""

from finance_agent.persistence.models import (
    DatabaseSummary,
    MigrationSummary,
    PersistedIngestionResult,
    PersistenceStatus,
    PersistenceSummary,
)
from finance_agent.persistence.repository import SQLiteFinanceRepository

__all__ = [
    "DatabaseSummary",
    "MigrationSummary",
    "PersistedIngestionResult",
    "PersistenceStatus",
    "PersistenceSummary",
    "SQLiteFinanceRepository",
]
