"""Regras de qualidade independentes do formato de cada banco."""

import re
import unicodedata


GENERIC_DESCRIPTION_TOKENS = {
    "BOLETO",
    "CARTAO",
    "COMPRA",
    "CREDITO",
    "DEBITO",
    "LANCAMENTO",
    "MASTERCARD",
    "PAGAMENTO",
    "PIX",
    "SAQUE",
    "SALDO",
    "TRANSFERENCIA",
    "VISA",
}


def normalize_description(value: str) -> str:
    """Cria texto comparável sem destruir o valor bruto original."""

    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    alphanumeric = re.sub(r"[^A-Za-z0-9]+", " ", without_accents)
    return " ".join(alphanumeric.upper().split())


def description_is_generic(value: str) -> bool:
    """Indica descrições que só dizem o meio/tipo, não o destino/origem."""

    normalized = normalize_description(value)
    if not normalized:
        return False
    tokens = set(normalized.split())
    return bool(tokens) and tokens.issubset(GENERIC_DESCRIPTION_TOKENS)
