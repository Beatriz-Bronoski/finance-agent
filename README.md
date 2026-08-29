# Finance Agent

Pipeline financeiro extensivel para importar, normalizar, reconciliar e classificar transacoes de diferentes instituicoes. O projeto adota uma arquitetura local-first: dados financeiros reais permanecem fora do repositorio e da demonstracao publica.

> Estado atual: Etapa 1 - fundacao segura e fixtures sinteticas.

## Objetivos

- Padronizar extratos de diferentes bancos em um schema canonico.
- Detectar perdas, ambiguidades e duplicidades sem decisoes silenciosas.
- Classificar transacoes por regras confirmadas antes de recorrer a IA.
- Permitir execucao privada local e demonstracao em nuvem apenas com dados ficticios.
- Manter portabilidade entre Azure e Google Cloud por meio de adaptadores.

## Seguranca dos dados

Este repositorio nao contem extratos, valores, nomes, contas ou identificadores reais. Os arquivos em `samples/synthetic/` foram criados do zero e existem apenas para reproduzir formatos e casos estruturais.

Nunca adicione dados reais ao Git. Coloque-os em `private_data/`, que e bloqueado pelo `.gitignore`. Consulte [SECURITY.md](SECURITY.md) e [docs/data-privacy.md](docs/data-privacy.md).

## Estrutura inicial

```text
finance-agent/
|-- src/finance_agent/
|-- tests/
|-- samples/synthetic/
|-- scripts/
|-- docs/
|-- .gitignore
|-- pyproject.toml
`-- README.md
```

## Fixtures sinteticas

- `picpay_demo_jul_ago_2026.csv`: estrutura equivalente a um export CSV, com credito, debito, sinal Unicode e duplicidade intencional.
- `bradesco_demo_jul_ago_2026.csv`: estrutura delimitada por ponto e virgula, com IDs variaveis, ID zero e historico contendo separador adicional.
- `bradesco_demo_jul_ago_2026.pdf`: PDF textual ficticio, incluindo uma transacao monetaria que comeca por texto para testar segmentacao.

Todos os nomes, valores, datas, documentos, contas e descricoes foram inventados.

## Preparacao local

Requer Python 3.11 ou 3.12.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
pytest
```

## Limites desta etapa

Ainda nao foram implementados parsers de producao, banco em nuvem, agente, OCR ou integracao com WhatsApp. A primeira etapa estabelece o contrato de privacidade e os casos de teste que orientarao essas implementacoes.

## Licenca

MIT. Veja [LICENSE](LICENSE).

