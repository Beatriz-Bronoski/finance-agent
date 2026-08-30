"""Promoção de candidatos válidos e preservação de pendências."""

from uuid import UUID

from finance_agent.domain.enums import DataQualityCode, IssueSeverity, PendingStatus
from finance_agent.domain.models import (
    CandidateCorrection,
    CandidateValidationResult,
    DataQualityIssue,
    PendingTransaction,
    Transaction,
    TransactionCandidate,
)
from finance_agent.domain.money import AmountDirectionError, normalize_signed_amount
from finance_agent.domain.quality import description_is_generic, normalize_description


def _issue(code: DataQualityCode, field: str, message: str) -> DataQualityIssue:
    return DataQualityIssue(
        code=code,
        field=field,
        severity=IssueSeverity.BLOCKING,
        message=message,
    )


def validate_candidate(candidate: TransactionCandidate, import_id: UUID) -> CandidateValidationResult:
    """Valida um registro sem depender do banco que o originou."""

    issues = list(candidate.extraction_issues)
    existing_codes = {item.code for item in issues}

    if candidate.transaction_date is None and not existing_codes.intersection(
        {
            DataQualityCode.MISSING_TRANSACTION_DATE,
            DataQualityCode.INVALID_TRANSACTION_DATE,
        }
    ):
        issues.append(
            _issue(
                DataQualityCode.MISSING_TRANSACTION_DATE,
                "transaction_date",
                "A data da transação é obrigatória.",
            )
        )

    signed_amount: int | None = None
    if candidate.amount_minor is None:
        if not existing_codes.intersection(
            {DataQualityCode.MISSING_AMOUNT, DataQualityCode.INVALID_AMOUNT}
        ):
            issues.append(
                _issue(
                    DataQualityCode.MISSING_AMOUNT,
                    "amount_minor",
                    "O valor da transação é obrigatório.",
                )
            )
    else:
        try:
            signed_amount = normalize_signed_amount(
                candidate.amount_minor,
                candidate.amount_direction,
            )
        except AmountDirectionError as exc:
            issue_map = {
                "zero_amount": (
                    DataQualityCode.ZERO_AMOUNT,
                    "O valor da transação não pode ser zero.",
                ),
                "ambiguous_amount_direction": (
                    DataQualityCode.AMBIGUOUS_AMOUNT_DIRECTION,
                    "Informe se o valor positivo é uma entrada ou uma saída.",
                ),
                "conflicting_amount_direction": (
                    DataQualityCode.CONFLICTING_AMOUNT_DIRECTION,
                    "O sinal do valor é incompatível com a direção informada.",
                ),
            }
            code, message = issue_map[exc.code]
            issues.append(_issue(code, "amount_minor", message))

    raw_description = candidate.description_raw or ""
    normalized_description = normalize_description(raw_description)
    if not normalized_description:
        if DataQualityCode.MISSING_DESCRIPTION not in existing_codes:
            issues.append(
                _issue(
                    DataQualityCode.MISSING_DESCRIPTION,
                    "description_raw",
                    "A descrição do destino ou da origem do dinheiro é obrigatória.",
                )
            )
    elif description_is_generic(raw_description):
        issues.append(
            _issue(
                DataQualityCode.GENERIC_DESCRIPTION_ONLY,
                "description_raw",
                "A descrição informa apenas o meio da transação, não seu destino ou origem.",
            )
        )

    blocking = [item for item in issues if item.severity == IssueSeverity.BLOCKING]
    if blocking:
        pending = PendingTransaction(import_id=import_id, candidate=candidate, issues=issues)
        return CandidateValidationResult(pending=pending, issues=issues)

    transaction = Transaction(
        import_id=import_id,
        transaction_date=candidate.transaction_date,
        transaction_time=candidate.transaction_time,
        amount_minor=signed_amount,
        description_raw=raw_description,
        description_normalized=normalized_description,
        source_institution=candidate.source_institution,
        source_location=candidate.source_location,
        source_record_hash=candidate.source_record_hash,
        external_id=candidate.external_id,
        balance_minor=candidate.balance_minor,
        payment_method=candidate.payment_method,
        payment_instrument=candidate.payment_instrument,
        card_alias=candidate.card_alias,
        card_last_four=candidate.card_last_four,
        source_account_ref=candidate.source_account_ref,
        counterparty_name=candidate.counterparty_name,
        merchant_name=candidate.merchant_name,
        source_metadata=candidate.source_metadata,
    )
    return CandidateValidationResult(transaction=transaction, issues=issues)


def apply_correction(
    pending: PendingTransaction,
    correction: CandidateCorrection,
) -> CandidateValidationResult:
    """Aplica uma correção de qualquer canal e revalida o candidato.

    O futuro agente do WhatsApp deve somente montar ``CandidateCorrection`` e
    chamar esta função. Ele não precisa conhecer regras de bancos ou de domínio.
    """

    if pending.status != PendingStatus.OPEN:
        raise ValueError("somente pendências abertas podem ser corrigidas")

    changes = correction.model_dump(exclude_unset=True, exclude_none=True)
    corrected_fields = set(changes)
    fields_to_codes = {
        "transaction_date": {
            DataQualityCode.MISSING_TRANSACTION_DATE,
            DataQualityCode.INVALID_TRANSACTION_DATE,
        },
        "amount_minor": {
            DataQualityCode.MISSING_AMOUNT,
            DataQualityCode.INVALID_AMOUNT,
            DataQualityCode.ZERO_AMOUNT,
            DataQualityCode.AMBIGUOUS_AMOUNT_DIRECTION,
            DataQualityCode.CONFLICTING_AMOUNT_DIRECTION,
        },
        "amount_direction": {
            DataQualityCode.AMBIGUOUS_AMOUNT_DIRECTION,
            DataQualityCode.CONFLICTING_AMOUNT_DIRECTION,
        },
        "description_raw": {
            DataQualityCode.MISSING_DESCRIPTION,
            DataQualityCode.GENERIC_DESCRIPTION_ONLY,
        },
    }
    cleared_codes = set().union(*(fields_to_codes[field] for field in corrected_fields))
    remaining_extraction_issues = [
        issue
        for issue in pending.candidate.extraction_issues
        if issue.code not in cleared_codes
    ]
    corrected_candidate = pending.candidate.model_copy(
        update={**changes, "extraction_issues": remaining_extraction_issues}
    )
    return validate_candidate(corrected_candidate, pending.import_id)
