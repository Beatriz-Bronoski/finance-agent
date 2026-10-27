"""Contratos HTTP em português, sem expor dados financeiros sensíveis."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finance_agent.classification.models import TransactionNature


class ModeloDaApi(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RespostaDeSaude(ModeloDaApi):
    situacao: Literal["disponivel"] = "disponivel"
    versao: str


class SolicitacaoDeCategoria(ModeloDaApi):
    nome: str = Field(min_length=1, max_length=80)


class SolicitacaoDeAtivacao(ModeloDaApi):
    ativa: bool


class RespostaDeCategoria(ModeloDaApi):
    id_categoria: UUID
    nome: str
    ativa: bool


class RespostaDeRegra(ModeloDaApi):
    id_regra: UUID
    nome: str
    prioridade: int
    natureza: TransactionNature
    id_categoria: UUID | None
    ativa: bool
    quantidade_criterios: int


class RespostaDaExecucao(ModeloDaApi):
    transacoes_examinadas: int
    transacoes_classificadas: int
    revisoes_criadas: int
    decisoes_preservadas: int


class RespostaDoResumo(ModeloDaApi):
    categorias_ativas: int
    regras_ativas: int
    transacoes_classificadas: int
    revisoes_abertas: int
    correcoes_registradas: int


class RespostaDeRevisao(ModeloDaApi):
    id_revisao: UUID
    id_transacao: UUID
    motivo: str
    quantidade_regras_candidatas: int


class SolicitacaoDeCorrecao(ModeloDaApi):
    natureza: TransactionNature
    categoria: str | None = Field(default=None, min_length=1, max_length=80)
    lembrar_correcao: bool = False
    prioridade_regra: int = Field(default=800, ge=1, le=1000)

    @model_validator(mode="after")
    def validar_categoria_obrigatoria(self) -> "SolicitacaoDeCorrecao":
        if (
            self.natureza in {TransactionNature.EXPENSE, TransactionNature.INCOME}
            and self.categoria is None
        ):
            raise ValueError("despesa e receita precisam de categoria")
        return self


class RespostaDeCorrecao(ModeloDaApi):
    id_transacao: UUID
    natureza: TransactionNature
    categoria: str | None
    regra_lembrada: bool
    id_regra_lembrada: UUID | None
