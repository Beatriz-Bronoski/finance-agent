from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from finance_agent.domain.enums import ImportStatus, IssueSeverity
from finance_agent.domain.models import (
    CandidateCorrection,
    DataQualityIssue,
    ImportResult,
    PendingTransaction,
    SourceLocation,
    TransactionCandidate,
)
from finance_agent.domain.enums import DataQualityCode


def candidate() -> TransactionCandidate:
    return TransactionCandidate(
        transaction_date=date(2026, 8, 1),
        amount_minor=-1000,
        description_raw="Mercado Aurora",
        source_institution="Banco Demo",
        source_location=SourceLocation(file_id=uuid4(), row_number=2),
        source_record_hash="a" * 64,
    )


def test_card_last_four_requires_exactly_four_digits() -> None:
    with pytest.raises(ValidationError):
        TransactionCandidate(
            **candidate().model_dump(exclude={"card_last_four"}),
            card_last_four="123",
        )

    with pytest.raises(ValidationError):
        TransactionCandidate(
            **candidate().model_dump(exclude={"card_last_four"}),
            card_last_four="12A4",
        )


def test_pending_requires_a_blocking_issue() -> None:
    warning = DataQualityIssue(
        code=DataQualityCode.DUPLICATE_CANDIDATE,
        severity=IssueSeverity.WARNING,
        message="Possível duplicidade.",
    )
    with pytest.raises(ValidationError):
        PendingTransaction(import_id=uuid4(), candidate=candidate(), issues=[warning])


def test_import_result_counts_must_balance() -> None:
    valid = ImportResult(
        import_id=uuid4(),
        status=ImportStatus.COMPLETED_WITH_WARNINGS,
        records_read=3,
        transactions_created=2,
        pending_created=1,
    )
    assert valid.records_read == 3

    with pytest.raises(ValidationError):
        ImportResult(
            import_id=uuid4(),
            status=ImportStatus.COMPLETED,
            records_read=3,
            transactions_created=2,
            pending_created=0,
        )


def test_empty_correction_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CandidateCorrection()
