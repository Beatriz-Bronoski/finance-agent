"""Vocabulário comum do domínio financeiro."""

from enum import Enum


class TransactionDirection(str, Enum):
    INFLOW = "inflow"
    OUTFLOW = "outflow"


class PaymentMethod(str, Enum):
    PIX = "pix"
    BANK_TRANSFER = "bank_transfer"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    CASH = "cash"
    DIGITAL_WALLET = "digital_wallet"
    BOLETO = "boleto"
    OTHER = "other"


class PaymentInstrument(str, Enum):
    BANK_ACCOUNT = "bank_account"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    WALLET = "wallet"
    CASH = "cash"
    OTHER = "other"


class ClassificationSource(str, Enum):
    RULE = "rule"
    MODEL = "model"
    USER = "user"


class IssueSeverity(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"


class DataQualityCode(str, Enum):
    MISSING_TRANSACTION_DATE = "missing_transaction_date"
    INVALID_TRANSACTION_DATE = "invalid_transaction_date"
    MISSING_AMOUNT = "missing_amount"
    INVALID_AMOUNT = "invalid_amount"
    ZERO_AMOUNT = "zero_amount"
    AMBIGUOUS_AMOUNT_DIRECTION = "ambiguous_amount_direction"
    CONFLICTING_AMOUNT_DIRECTION = "conflicting_amount_direction"
    MISSING_DESCRIPTION = "missing_description"
    GENERIC_DESCRIPTION_ONLY = "generic_description_only"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    UNSUPPORTED_RECORD = "unsupported_record"


class PendingStatus(str, Enum):
    OPEN = "open"
    CORRECTED = "corrected"
    DISCARDED = "discarded"


class ImportStatus(str, Enum):
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
