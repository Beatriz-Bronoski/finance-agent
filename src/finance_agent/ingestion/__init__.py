"""API pública da camada de ingestão."""

from finance_agent.ingestion.models import (
    ColumnMapping,
    CsvSchemaProfile,
    DetectionResult,
    DetectionStatus,
    IngestionOutcome,
    IngestionStatus,
    MappingSuggestion,
    SchemaDriftReport,
)
from finance_agent.ingestion.registry import MappingRegistry
from finance_agent.ingestion.schema import (
    FormatDetector,
    SchemaDriftDetector,
    SchemaProfiler,
    suggest_column_mapping,
)

__all__ = [
    "ColumnMapping",
    "CsvSchemaProfile",
    "DetectionResult",
    "DetectionStatus",
    "FormatDetector",
    "IngestionOutcome",
    "IngestionStatus",
    "MappingRegistry",
    "MappingSuggestion",
    "SchemaDriftDetector",
    "SchemaDriftReport",
    "SchemaProfiler",
    "suggest_column_mapping",
]
