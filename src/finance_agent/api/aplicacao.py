"""Aplicação FastAPI local e deliberadamente pequena para o MVP."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, status

from finance_agent import __version__
from finance_agent.api.modelos import (
    RespostaDaExecucao,
    RespostaDeCategoria,
    RespostaDeCorrecao,
    RespostaDeRegra,
    RespostaDeRevisao,
    RespostaDeSaude,
    RespostaDoResumo,
    SolicitacaoDeAtivacao,
    SolicitacaoDeCategoria,
    SolicitacaoDeCorrecao,
)
from finance_agent.classification.engine import classificar_transacoes_pendentes
from finance_agent.classification.models import Category, ClassificationRule
from finance_agent.persistence import SQLiteClassificationRepository


def obter_repositorio() -> SQLiteClassificationRepository:
    """Abre o repositório no banco privado padrão."""

    return SQLiteClassificationRepository()


RepositorioDaApi = Annotated[
    SQLiteClassificationRepository,
    Depends(obter_repositorio),
]
LimiteDaApi = Annotated[int, Query(ge=1, le=1000)]


def _converter_categoria(categoria: Category) -> RespostaDeCategoria:
    return RespostaDeCategoria(
        id_categoria=categoria.id,
        nome=categoria.name,
        ativa=categoria.is_active,
    )


def _converter_regra(regra: ClassificationRule) -> RespostaDeRegra:
    return RespostaDeRegra(
        id_regra=regra.id,
        nome=regra.name,
        prioridade=regra.priority,
        natureza=regra.nature,
        id_categoria=regra.category_id,
        ativa=regra.is_enabled,
        quantidade_criterios=regra.calcular_quantidade_de_criterios,
    )


def criar_aplicacao() -> FastAPI:
    """Monta a API e permite substituir dependências nos testes."""

    app = FastAPI(
        title="Finance Agent API",
        description="API local do MVP para classificação financeira.",
        version=__version__,
    )

    @app.get("/saude", response_model=RespostaDeSaude, tags=["sistema"])
    def verificar_saude() -> RespostaDeSaude:
        return RespostaDeSaude(versao=__version__)

    @app.get("/categorias", response_model=list[RespostaDeCategoria], tags=["categorias"])
    def listar_categorias(
        repositorio: RepositorioDaApi,
        somente_ativas: bool = False,
    ) -> list[RespostaDeCategoria]:
        categorias = repositorio.list_categories(active_only=somente_ativas)
        return [_converter_categoria(categoria) for categoria in categorias]

    @app.post(
        "/categorias",
        response_model=RespostaDeCategoria,
        status_code=status.HTTP_201_CREATED,
        tags=["categorias"],
    )
    def criar_categoria(
        solicitacao: SolicitacaoDeCategoria,
        repositorio: RepositorioDaApi,
    ) -> RespostaDeCategoria:
        return _converter_categoria(repositorio.create_category(solicitacao.nome))

    @app.patch(
        "/categorias/{id_categoria}",
        response_model=RespostaDeCategoria,
        tags=["categorias"],
    )
    def alterar_categoria(
        id_categoria: UUID,
        solicitacao: SolicitacaoDeAtivacao,
        repositorio: RepositorioDaApi,
    ) -> RespostaDeCategoria:
        if not repositorio.set_category_active(id_categoria, active=solicitacao.ativa):
            raise HTTPException(status_code=404, detail="categoria_nao_encontrada")
        categoria = next(item for item in repositorio.list_categories() if item.id == id_categoria)
        return _converter_categoria(categoria)

    @app.get("/regras", response_model=list[RespostaDeRegra], tags=["regras"])
    def listar_regras(
        repositorio: RepositorioDaApi,
        somente_ativas: bool = False,
    ) -> list[RespostaDeRegra]:
        regras = repositorio.list_rules(enabled_only=somente_ativas)
        return [_converter_regra(regra) for regra in regras]

    @app.patch("/regras/{id_regra}", response_model=RespostaDeRegra, tags=["regras"])
    def alterar_regra(
        id_regra: UUID,
        solicitacao: SolicitacaoDeAtivacao,
        repositorio: RepositorioDaApi,
    ) -> RespostaDeRegra:
        if not repositorio.set_rule_enabled(id_regra, enabled=solicitacao.ativa):
            raise HTTPException(status_code=404, detail="regra_nao_encontrada")
        regra = next(item for item in repositorio.list_rules() if item.id == id_regra)
        return _converter_regra(regra)

    @app.post(
        "/classificacoes/executar",
        response_model=RespostaDaExecucao,
        tags=["classificacoes"],
    )
    def executar_classificacao(
        repositorio: RepositorioDaApi,
        limite: LimiteDaApi = 500,
    ) -> RespostaDaExecucao:
        resumo = classificar_transacoes_pendentes(repositorio, limite=limite)
        return RespostaDaExecucao(
            transacoes_examinadas=resumo.examined,
            transacoes_classificadas=resumo.classified,
            revisoes_criadas=resumo.pending_review,
            decisoes_preservadas=resumo.skipped_with_decision,
        )

    @app.get(
        "/classificacoes/resumo",
        response_model=RespostaDoResumo,
        tags=["classificacoes"],
    )
    def obter_resumo(
        repositorio: RepositorioDaApi,
    ) -> RespostaDoResumo:
        resumo = repositorio.classification_summary()
        return RespostaDoResumo(
            categorias_ativas=resumo.active_categories,
            regras_ativas=resumo.enabled_rules,
            transacoes_classificadas=resumo.classified_transactions,
            revisoes_abertas=resumo.open_reviews,
            correcoes_registradas=resumo.corrections,
        )

    @app.get(
        "/revisoes/pendentes",
        response_model=list[RespostaDeRevisao],
        tags=["revisoes"],
    )
    def listar_revisoes_pendentes(
        repositorio: RepositorioDaApi,
        limite: LimiteDaApi = 100,
    ) -> list[RespostaDeRevisao]:
        revisoes = repositorio.list_open_reviews(limit=limite)
        return [
            RespostaDeRevisao(
                id_revisao=revisao.id,
                id_transacao=revisao.transaction_id,
                motivo=revisao.reason.value,
                quantidade_regras_candidatas=len(revisao.candidate_rule_ids),
            )
            for revisao in revisoes
        ]

    @app.post(
        "/transacoes/{id_transacao}/corrigir",
        response_model=RespostaDeCorrecao,
        tags=["classificacoes"],
    )
    def corrigir_classificacao(
        id_transacao: UUID,
        solicitacao: SolicitacaoDeCorrecao,
        repositorio: RepositorioDaApi,
    ) -> RespostaDeCorrecao:
        try:
            resultado = repositorio.correct_classification(
                id_transacao,
                nature=solicitacao.natureza,
                category_name=solicitacao.categoria,
                remember=solicitacao.lembrar_correcao,
                rule_priority=solicitacao.prioridade_regra,
            )
        except ValueError as erro:
            detalhe = str(erro)
            codigo = 404 if detalhe == "transaction_not_found" else 400
            raise HTTPException(status_code=codigo, detail=detalhe) from erro
        return RespostaDeCorrecao(
            id_transacao=resultado.decision.transaction_id,
            natureza=resultado.decision.nature,
            categoria=resultado.decision.category_name,
            regra_lembrada=resultado.remembered_rule_id is not None,
            id_regra_lembrada=resultado.remembered_rule_id,
        )

    return app


aplicacao = criar_aplicacao()
