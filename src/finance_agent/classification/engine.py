"""Motor determinístico: maior prioridade vence; empate divergente exige revisão."""

from __future__ import annotations

from finance_agent.classification.models import (
    ClassificationProposal,
    ClassificationRule,
    ClassificationRunSummary,
    ClassificationStatus,
    ReviewReason,
)
from finance_agent.domain.models import ClassificationContext
from finance_agent.persistence.classification_repository import SQLiteClassificationRepository


def classificar_contexto(
    contexto: ClassificationContext,
    regras: list[ClassificationRule],
) -> ClassificationProposal:
    """Produz uma decisão explicável sem gravar ou alterar dados."""

    regras_correspondentes = [
        regra
        for regra in regras
        if regra.is_enabled and regra.verificar_correspondencia(contexto)
    ]
    if not regras_correspondentes:
        return ClassificationProposal(
            status=ClassificationStatus.PENDING_REVIEW,
            review_reason=ReviewReason.NO_MATCHING_RULE,
        )

    maior_prioridade = max(regra.priority for regra in regras_correspondentes)
    regras_vencedoras = sorted(
        (
            regra
            for regra in regras_correspondentes
            if regra.priority == maior_prioridade
        ),
        key=lambda regra: str(regra.id),
    )
    classificacoes_resultantes = {
        (regra.nature, regra.category_id)
        for regra in regras_vencedoras
    }
    ids_das_regras_vencedoras = [regra.id for regra in regras_vencedoras]
    if len(classificacoes_resultantes) > 1:
        return ClassificationProposal(
            status=ClassificationStatus.PENDING_REVIEW,
            matched_rule_ids=ids_das_regras_vencedoras,
            review_reason=ReviewReason.PRIORITY_CONFLICT,
        )

    regra_selecionada = regras_vencedoras[0]
    return ClassificationProposal(
        status=ClassificationStatus.CLASSIFIED,
        nature=regra_selecionada.nature,
        category_id=regra_selecionada.category_id,
        winning_rule_id=regra_selecionada.id,
        matched_rule_ids=ids_das_regras_vencedoras,
    )


def classificar_transacoes_pendentes(
    repositorio: SQLiteClassificationRepository,
    *,
    limite: int = 500,
) -> ClassificationRunSummary:
    """Classifica apenas itens sem decisão atual; nunca reescreve histórico confirmado."""

    transacoes, ignoradas = repositorio.list_transactions_for_classification(
        limit=limite
    )
    regras = repositorio.list_rules(enabled_only=True)
    quantidade_classificadas = 0
    quantidade_pendentes = 0
    for transacao in transacoes:
        proposta = classificar_contexto(
            ClassificationContext.from_transaction(transacao),
            regras,
        )
        if proposta.status == ClassificationStatus.CLASSIFIED:
            repositorio.record_rule_decision(transacao.id, proposta)
            quantidade_classificadas += 1
            continue
        repositorio.open_review(
            transacao.id,
            proposta.review_reason or ReviewReason.NO_MATCHING_RULE,
            proposta.matched_rule_ids,
        )
        quantidade_pendentes += 1

    return ClassificationRunSummary(
        examined=len(transacoes),
        classified=quantidade_classificadas,
        pending_review=quantidade_pendentes,
        skipped_with_decision=ignoradas,
    )
