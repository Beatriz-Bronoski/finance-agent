"""Dependências substituíveis da API local."""

from finance_agent.persistence import SQLiteClassificationRepository


def obter_repositorio() -> SQLiteClassificationRepository:
    """Abre o repositório no banco privado padrão."""

    return SQLiteClassificationRepository()
