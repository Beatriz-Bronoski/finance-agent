from datetime import date
from uuid import UUID, uuid4

import pytest

from finance_agent.application import apply_correction, validate_candidate
from finance_agent.domain.enums import (
    DataQualityCode,
    PaymentInstrument,
    PaymentMethod,
    TransactionDirection,
)
from finance_agent.domain.models import (
    CandidateCorrection,
    ClassificationContext,
    DataQualityIssue,
    SourceLocation,
    TransactionCandidate,
)


IMPORT_ID = UUID("11111111-1111-1111-1111-111111111111")


def candidate(**overrides: object) -> TransactionCandidate:
    values: dict[str, object] = {
        "transaction_date": date(2026, 8, 10),
        "amount_minor": -4875,
        "description_raw": "Mercado Aurora cartão",
        "source_institution": "Banco Demo",
        "source_location": SourceLocation(file_id=uuid4(), row_number=4),
        "source_record_hash": "b" * 64,
    }
    values.update(overrides)
    return TransactionCandidate(**values)


def issue_codes(result: object) -> set[DataQualityCode]:
    return {issue.code for issue in result.issues}  # type: ignore[attr-defined]


def test_minimum_fields_create_a_canonical_transaction() -> None:
    result = validate_candidate(candidate(), IMPORT_ID)

    assert result.is_valid
    assert result.transaction is not None
    assert result.transaction.amount_minor == -4875
    assert result.transaction.description_normalized == "MERCADO AURORA CARTAO"


def test_positive_value_needs_explicit_direction() -> None:
    result = validate_candidate(candidate(amount_minor=4875), IMPORT_ID)

    assert not result.is_valid
    assert DataQualityCode.AMBIGUOUS_AMOUNT_DIRECTION in issue_codes(result)


def test_explicit_inflow_preserves_positive_amount() -> None:
    result = validate_candidate(
        candidate(amount_minor=4875, amount_direction=TransactionDirection.INFLOW),
        IMPORT_ID,
    )

    assert result.transaction is not None
    assert result.transaction.amount_minor == 4875


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"transaction_date": None}, DataQualityCode.MISSING_TRANSACTION_DATE),
        ({"amount_minor": None}, DataQualityCode.MISSING_AMOUNT),
        ({"amount_minor": 0}, DataQualityCode.ZERO_AMOUNT),
        ({"description_raw": None}, DataQualityCode.MISSING_DESCRIPTION),
        ({"description_raw": "CARTÃO VISA"}, DataQualityCode.GENERIC_DESCRIPTION_ONLY),
    ],
)
def test_invalid_minimum_data_becomes_pending(
    overrides: dict[str, object],
    expected_code: DataQualityCode,
) -> None:
    result = validate_candidate(candidate(**overrides), IMPORT_ID)

    assert result.pending is not None
    assert expected_code in issue_codes(result)


def test_invalid_extraction_issue_is_preserved_without_missing_duplicate() -> None:
    invalid = DataQualityIssue(
        code=DataQualityCode.INVALID_TRANSACTION_DATE,
        field="transaction_date",
        message="A data não pôde ser interpretada.",
    )
    result = validate_candidate(
        candidate(transaction_date=None, extraction_issues=[invalid]),
        IMPORT_ID,
    )

    assert issue_codes(result) == {DataQualityCode.INVALID_TRANSACTION_DATE}


def test_card_is_optional_context_and_never_replaces_description() -> None:
    result = validate_candidate(
        candidate(
            card_alias="Cartão principal",
            card_last_four="1234",
            payment_method=PaymentMethod.CREDIT_CARD,
            payment_instrument=PaymentInstrument.CREDIT_CARD,
        ),
        IMPORT_ID,
    )

    assert result.transaction is not None
    assert result.transaction.description_raw == "Mercado Aurora cartão"
    assert result.transaction.card_alias == "Cartão principal"
    assert result.transaction.card_last_four == "1234"


def test_channel_neutral_correction_promotes_pending_to_transaction() -> None:
    first_result = validate_candidate(candidate(description_raw=None), IMPORT_ID)
    assert first_result.pending is not None

    corrected = apply_correction(
        first_result.pending,
        CandidateCorrection(description_raw="Farmácia Horizonte"),
    )

    assert corrected.transaction is not None
    assert corrected.transaction.description_normalized == "FARMACIA HORIZONTE"
    assert first_result.pending.mark_corrected().status.value == "corrected"


def test_classification_context_excludes_traceability_and_bank_metadata() -> None:
    result = validate_candidate(
        candidate(
            source_account_ref="internal-account-reference",
            external_id="bank-event-id",
            source_metadata={"bank_private_column": "not-for-model"},
            merchant_name="Mercado Aurora",
        ),
        IMPORT_ID,
    )
    assert result.transaction is not None

    context = ClassificationContext.from_transaction(result.transaction)
    exposed = context.model_dump()

    assert exposed["merchant_name"] == "Mercado Aurora"
    assert "source_account_ref" not in exposed
    assert "external_id" not in exposed
    assert "source_metadata" not in exposed
