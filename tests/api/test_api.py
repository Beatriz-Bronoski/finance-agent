from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from finance_agent import __version__
from finance_agent.api import criar_aplicacao
from finance_agent.api.dependencias import obter_repositorio
from finance_agent.application import ingest_and_persist
from finance_agent.classification.models import DecisionSource
from finance_agent.persistence import SQLiteClassificationRepository

ROOT = Path(__file__).resolve().parents[2]
PICPAY = ROOT / "samples" / "synthetic" / "picpay_demo_jul_ago_2026.csv"


@pytest.fixture
def preparar_api(
    tmp_path: Path,
) -> tuple[TestClient, SQLiteClassificationRepository]:
    banco = tmp_path / "finance.db"
    ingest_and_persist(
        PICPAY,
        database_path=banco,
        registry_path=tmp_path / "registry.json",
    )
    repositorio = SQLiteClassificationRepository(banco)
    aplicacao = criar_aplicacao()
    aplicacao.dependency_overrides[obter_repositorio] = lambda: repositorio
    return TestClient(aplicacao), repositorio


def test_informa_saude_e_publica_documentacao(
    preparar_api: tuple[TestClient, SQLiteClassificationRepository],
) -> None:
    cliente, _ = preparar_api

    resposta = cliente.get("/saude")

    assert resposta.status_code == 200
    assert resposta.json() == {"situacao": "disponivel", "versao": __version__}
    assert cliente.get("/docs").status_code == 200
    assert cliente.get("/openapi.json").status_code == 200


def test_cria_lista_e_desativa_categoria(
    preparar_api: tuple[TestClient, SQLiteClassificationRepository],
) -> None:
    cliente, _ = preparar_api

    criada = cliente.post("/categorias", json={"nome": "Alimentação"})
    id_categoria = criada.json()["id_categoria"]
    desativada = cliente.patch(
        f"/categorias/{id_categoria}",
        json={"ativa": False},
    )

    assert criada.status_code == 201
    assert criada.json()["nome"] == "Alimentação"
    assert desativada.status_code == 200
    assert desativada.json()["ativa"] is False
    assert cliente.get("/categorias?somente_ativas=true").json() == []
    assert (
        cliente.patch(
            f"/categorias/{uuid4()}",
            json={"ativa": True},
        ).status_code
        == 404
    )


def test_executa_classificacao_e_lista_revisoes_sem_expor_dados_financeiros(
    preparar_api: tuple[TestClient, SQLiteClassificationRepository],
) -> None:
    cliente, _ = preparar_api

    resposta = cliente.post("/classificacoes/executar")
    revisoes = cliente.get("/revisoes/pendentes")
    conteudo = revisoes.text

    assert resposta.status_code == 200
    assert resposta.json() == {
        "transacoes_examinadas": 11,
        "transacoes_classificadas": 0,
        "revisoes_criadas": 11,
        "decisoes_preservadas": 0,
    }
    assert revisoes.status_code == 200
    assert len(revisoes.json()) == 11
    assert set(revisoes.json()[0]) == {
        "id_revisao",
        "id_transacao",
        "motivo",
        "quantidade_regras_candidatas",
    }
    assert "MERCADO FICTICIO AURORA" not in conteudo
    assert "48,75" not in conteudo
    assert cliente.post("/classificacoes/executar?limite=0").status_code == 422


def test_corrige_classificacao_lembra_regra_e_preserva_decisao(
    preparar_api: tuple[TestClient, SQLiteClassificationRepository],
) -> None:
    cliente, repositorio = preparar_api
    cliente.post("/categorias", json={"nome": "Alimentação"})
    cliente.post("/classificacoes/executar")
    transacao = repositorio.list_transactions_for_classification()[0][0]

    corrigida = cliente.post(
        f"/transacoes/{transacao.id}/corrigir",
        json={
            "natureza": "despesa",
            "categoria": "Alimentação",
            "lembrar_correcao": True,
        },
    )
    decisao_antes = repositorio.get_current_decision(transacao.id)
    nova_execucao = cliente.post("/classificacoes/executar")
    decisao_depois = repositorio.get_current_decision(transacao.id)
    resumo = cliente.get("/classificacoes/resumo").json()
    regras = cliente.get("/regras").json()

    assert corrigida.status_code == 200
    assert corrigida.json()["regra_lembrada"] is True
    assert corrigida.json()["categoria"] == "Alimentação"
    assert decisao_antes is not None
    assert decisao_antes.source == DecisionSource.USER
    assert decisao_depois == decisao_antes
    assert nova_execucao.json()["decisoes_preservadas"] >= 1
    assert resumo["correcoes_registradas"] == 1
    assert resumo["regras_ativas"] == 1
    assert set(regras[0]) == {
        "id_regra",
        "nome",
        "prioridade",
        "natureza",
        "id_categoria",
        "ativa",
        "quantidade_criterios",
    }
    assert transacao.description_normalized not in cliente.get("/regras").text


def test_altera_regra_sem_expor_seus_criterios(
    preparar_api: tuple[TestClient, SQLiteClassificationRepository],
) -> None:
    cliente, repositorio = preparar_api
    cliente.post("/categorias", json={"nome": "Alimentação"})
    transacao = repositorio.list_transactions_for_classification()[0][0]
    cliente.post(
        f"/transacoes/{transacao.id}/corrigir",
        json={
            "natureza": "despesa",
            "categoria": "Alimentação",
            "lembrar_correcao": True,
        },
    )
    id_regra = cliente.get("/regras").json()[0]["id_regra"]

    resposta = cliente.patch(f"/regras/{id_regra}", json={"ativa": False})

    assert resposta.status_code == 200
    assert resposta.json()["ativa"] is False
    assert cliente.get("/regras?somente_ativas=true").json() == []
    assert cliente.patch(f"/regras/{uuid4()}", json={"ativa": True}).status_code == 404


def test_rejeita_correcao_invalida_com_erros_http_seguros(
    preparar_api: tuple[TestClient, SQLiteClassificationRepository],
) -> None:
    cliente, repositorio = preparar_api
    transacao = repositorio.list_transactions_for_classification()[0][0]

    sem_categoria = cliente.post(
        f"/transacoes/{transacao.id}/corrigir",
        json={"natureza": "despesa"},
    )
    inexistente = cliente.post(
        f"/transacoes/{uuid4()}/corrigir",
        json={"natureza": "transferencia_interna"},
    )

    assert sem_categoria.status_code == 422
    assert inexistente.status_code == 404
    assert inexistente.json() == {"detail": "transaction_not_found"}
    assert transacao.description_normalized not in inexistente.text
