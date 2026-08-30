"""Orquestração da ingestão sem persistência e sem dependência de nuvem."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path
from uuid import UUID, uuid4

from finance_agent.application.candidate_validator import validate_candidate
from finance_agent.domain.enums import ImportStatus
from finance_agent.domain.models import ImportBatch, ImportResult
from finance_agent.ingestion.models import (
    DetectionStatus,
    IngestionIssueCode,
    IngestionOutcome,
    IngestionStatus,
    IngestionSummary,
    MappingSuggestion,
)
from finance_agent.ingestion.parsers import parser_for_spec
from finance_agent.ingestion.registry import MappingRegistry, RegistryError
from finance_agent.ingestion.schema import (
    FormatDetector,
    SchemaDriftDetector,
    SchemaProfileError,
    SchemaProfiler,
)


DEFAULT_REGISTRY_PATH = Path("private_data/config/bank_mappings.json")
SUPPORTED_SUFFIXES = {".csv", ".txt"}


def _blocked_outcome(
    import_id: UUID,
    detection_status: DetectionStatus,
    issue_code: IngestionIssueCode,
    suggestion: MappingSuggestion | None = None,
) -> IngestionOutcome:
    return IngestionOutcome(
        summary=IngestionSummary(
            import_id=import_id,
            status=IngestionStatus.BLOCKED,
            detection_status=detection_status,
            issue_counts={issue_code.value: 1},
        ),
        suggested_mapping=suggestion,
    )


def ingest_file(
    path: str | Path,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    approve_generic_as: str | None = None,
    generic_currency: str | None = None,
    generic_date_order: str | None = None,
) -> IngestionOutcome:
    """Detecta, interpreta e valida um arquivo sem gravar transações em banco."""

    import_id = uuid4()
    source_path = Path(path)
    if source_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        return _blocked_outcome(
            import_id,
            DetectionStatus.UNKNOWN,
            IngestionIssueCode.UNSUPPORTED_FILE_TYPE,
        )

    try:
        profile = SchemaProfiler().profile(source_path)
    except SchemaProfileError as exc:
        return _blocked_outcome(import_id, DetectionStatus.UNKNOWN, exc.code)
    except OSError:
        return IngestionOutcome(
            summary=IngestionSummary(
                import_id=import_id,
                status=IngestionStatus.FAILED,
                detection_status=DetectionStatus.UNKNOWN,
                issue_counts={IngestionIssueCode.UNREADABLE_FILE.value: 1},
            )
        )

    registry = MappingRegistry(Path(registry_path))
    try:
        learned_specs = registry.list_specs()
    except RegistryError:
        return _blocked_outcome(
            import_id,
            DetectionStatus.UNKNOWN,
            IngestionIssueCode.REGISTRY_INVALID,
        )

    detection = FormatDetector(learned_specs).detect(profile)
    if detection.status == DetectionStatus.AMBIGUOUS:
        return _blocked_outcome(
            import_id,
            detection.status,
            IngestionIssueCode.AMBIGUOUS_FORMAT,
        )
    if detection.status == DetectionStatus.UNKNOWN:
        return _blocked_outcome(
            import_id,
            detection.status,
            IngestionIssueCode.MISSING_MINIMUM_COLUMN,
            detection.suggested_mapping,
        )
    if detection.status == DetectionStatus.GENERIC:
        if approve_generic_as is None:
            return _blocked_outcome(
                import_id,
                detection.status,
                IngestionIssueCode.GENERIC_MAPPING_REQUIRES_APPROVAL,
                detection.suggested_mapping,
            )
        if generic_currency is None:
            return _blocked_outcome(
                import_id,
                detection.status,
                IngestionIssueCode.MISSING_CURRENCY,
                detection.suggested_mapping,
            )
        if detection.suggested_mapping is None:
            return _blocked_outcome(
                import_id,
                detection.status,
                IngestionIssueCode.MISSING_MINIMUM_COLUMN,
            )
        try:
            selected_spec = registry.learn(
                profile,
                detection.suggested_mapping.mapping,
                approve_generic_as,
                generic_currency,
                generic_date_order,
            )
        except RegistryError:
            return _blocked_outcome(
                import_id,
                detection.status,
                IngestionIssueCode.REGISTRY_INVALID,
                detection.suggested_mapping,
            )
        detection_status = DetectionStatus.LEARNED
    else:
        selected_spec = detection.selected_spec
        detection_status = detection.status

    if selected_spec is None:
        return _blocked_outcome(
            import_id,
            detection_status,
            IngestionIssueCode.UNKNOWN_FORMAT,
        )

    drift = SchemaDriftDetector().compare(profile, selected_spec)
    if drift.is_breaking:
        counts = Counter(change.code.value for change in drift.changes)
        return IngestionOutcome(
            summary=IngestionSummary(
                import_id=import_id,
                status=IngestionStatus.BLOCKED,
                detection_status=detection_status,
                format_id=selected_spec.format_id,
                institution=selected_spec.institution,
                issue_counts=dict(counts),
                drift=drift,
            )
        )

    source_hash = profile.source_file_hash
    batch = ImportBatch(
        id=import_id,
        source_file_hash=source_hash,
        source_institution=selected_spec.institution,
    )
    parser = parser_for_spec(selected_spec)
    try:
        parsed = parser.parse(source_path, profile, selected_spec)
    except (OSError, UnicodeError, csv.Error):
        return IngestionOutcome(
            summary=IngestionSummary(
                import_id=batch.id,
                status=IngestionStatus.FAILED,
                detection_status=detection_status,
                format_id=selected_spec.format_id,
                institution=selected_spec.institution,
                issue_counts={IngestionIssueCode.UNREADABLE_FILE.value: 1},
                drift=drift,
            )
        )

    try:
        final_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    except OSError:
        final_hash = ""
    if final_hash != source_hash:
        return IngestionOutcome(
            summary=IngestionSummary(
                import_id=batch.id,
                status=IngestionStatus.FAILED,
                detection_status=detection_status,
                format_id=selected_spec.format_id,
                institution=selected_spec.institution,
                issue_counts={IngestionIssueCode.FILE_CHANGED_DURING_READ.value: 1},
                drift=drift,
            )
        )

    issue_counts: Counter[str] = Counter()
    for diagnostic in parsed.diagnostics:
        issue_counts[diagnostic.code.value] += 1
    for change in drift.changes:
        issue_counts[change.code.value] += 1

    transactions = []
    pending = []
    duplicates = 0
    seen_hashes: set[str] = set()
    for candidate in parsed.candidates:
        if candidate.source_record_hash in seen_hashes:
            duplicates += 1
            issue_counts[IngestionIssueCode.DUPLICATE_RECORD.value] += 1
            continue
        seen_hashes.add(candidate.source_record_hash)
        validation = validate_candidate(candidate, batch.id)
        for issue in validation.issues:
            issue_counts[issue.code.value] += 1
        if validation.transaction is not None:
            transactions.append(validation.transaction)
        elif validation.pending is not None:
            pending.append(validation.pending)

    domain_status = (
        ImportStatus.COMPLETED_WITH_WARNINGS
        if issue_counts
        else ImportStatus.COMPLETED
    )
    ImportResult(
        import_id=batch.id,
        status=domain_status,
        records_read=parsed.records_read,
        transactions_created=len(transactions),
        pending_created=len(pending),
        records_rejected=parsed.rejected_count + duplicates,
    )
    ingestion_status = (
        IngestionStatus.COMPLETED_WITH_ISSUES
        if issue_counts
        else IngestionStatus.COMPLETED
    )
    summary = IngestionSummary(
        import_id=batch.id,
        status=ingestion_status,
        detection_status=detection_status,
        format_id=selected_spec.format_id,
        institution=selected_spec.institution,
        records_read=parsed.records_read,
        transactions_created=len(transactions),
        pending_created=len(pending),
        duplicates_found=duplicates,
        records_rejected=parsed.rejected_count,
        issue_counts=dict(sorted(issue_counts.items())),
        drift=drift,
    )
    return IngestionOutcome(summary=summary, transactions=transactions, pending=pending)


def safe_summary_lines(outcome: IngestionOutcome) -> list[str]:
    """Retorna somente contagens e códigos; nunca linhas ou valores do extrato."""

    summary = outcome.summary
    lines = [
        f"Status: {summary.status.value}",
        f"Detecção: {summary.detection_status.value}",
        f"Formato: {summary.format_id or 'não identificado'}",
        f"Instituição: {summary.institution or 'não identificada'}",
        f"Registros lidos: {summary.records_read}",
        f"Transações válidas: {summary.transactions_created}",
        f"Pendências: {summary.pending_created}",
        f"Duplicidades: {summary.duplicates_found}",
        f"Registros rejeitados: {summary.records_rejected}",
    ]
    if summary.issue_counts:
        encoded = ", ".join(
            f"{code}={count}" for code, count in sorted(summary.issue_counts.items())
        )
        lines.append(f"Alertas: {encoded}")
    if outcome.suggested_mapping is not None:
        mapping = outcome.suggested_mapping.mapping.model_dump(exclude_none=True)
        encoded_mapping = ", ".join(f"{field}<-{column}" for field, column in mapping.items())
        lines.append(f"Mapeamento sugerido: {encoded_mapping}")
        lines.append(f"Confiança do mapeamento: {outcome.suggested_mapping.confidence:.0%}")
    return lines
