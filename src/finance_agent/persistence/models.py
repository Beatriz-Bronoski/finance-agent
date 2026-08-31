"""Contratos públicos da persistência SQLite."""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from finance_agent.ingestion.models import IngestionOutcome


class PersistenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PersistenceStatus(str, Enum):
    STORED = "stored"
    ALREADY_IMPORTED = "already_imported"
    NOT_STORED = "not_stored"
    FAILED = "failed"


class MigrationSummary(PersistenceModel):
    schema_version: int = Field(ge=0)
    migrations_applied: int = Field(ge=0)


class DatabaseSummary(PersistenceModel):
    schema_version: int = Field(ge=0)
    import_attempts: int = Field(ge=0)
    completed_imports: int = Field(ge=0)
    transactions: int = Field(ge=0)
    open_pending: int = Field(ge=0)
    duplicate_candidates: int = Field(ge=0)


class PersistenceSummary(PersistenceModel):
    import_id: UUID
    status: PersistenceStatus
    transactions_inserted: int = Field(default=0, ge=0)
    pending_inserted: int = Field(default=0, ge=0)
    cross_file_duplicates: int = Field(default=0, ge=0)
    database_summary: DatabaseSummary
    error_code: str | None = None


class PersistedIngestionResult(PersistenceModel):
    ingestion: IngestionOutcome | None = None
    persistence: PersistenceSummary
