# Finance Agent

Pipeline financeiro extensivel para importar, normalizar, reconciliar e classificar transacoes de diferentes instituicoes. O projeto adota uma arquitetura local-first: dados financeiros reais permanecem fora do repositorio e da demonstracao publica.

> Estado atual: Etapa 4 - persistência SQLite segura, versionada e idempotente.

## Objetivos

- Padronizar extratos de diferentes bancos em um schema canonico.
- Detectar perdas, ambiguidades e duplicidades sem decisoes silenciosas.
- Classificar transacoes por regras confirmadas antes de recorrer a IA.
- Permitir execucao privada local e demonstracao em nuvem apenas com dados ficticios.
- Manter portabilidade entre Azure e Google Cloud por meio de adaptadores.

## Seguranca dos dados

Este repositorio nao contem extratos, valores, nomes, contas ou identificadores reais. Os arquivos em `samples/synthetic/` foram criados do zero e existem apenas para reproduzir formatos e casos estruturais.

Nunca adicione dados reais ao Git. Coloque-os em `private_data/`, que e bloqueado pelo `.gitignore`. Consulte [SECURITY.md](SECURITY.md) e [docs/data-privacy.md](docs/data-privacy.md).

## Estrutura atual

```text
finance-agent/
|-- src/finance_agent/domain/
|-- src/finance_agent/application/
|-- src/finance_agent/ingestion/
|-- src/finance_agent/persistence/
|-- tests/domain/
|-- tests/application/
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

Requer Python 3.11, 3.12 ou 3.13.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
pytest
```

## Etapa 3: ingestão local

O comando abaixo detecta o formato, interpreta o CSV e exibe somente contagens e
códigos de alerta. Nenhuma transação é persistida nesta etapa.

```bash
finance-agent ingest samples/synthetic/picpay_demo_jul_ago_2026.csv
finance-agent ingest samples/synthetic/bradesco_demo_jul_ago_2026.csv
```

Um CSV desconhecido com colunas mínimas recebe uma sugestão, mas não é processado
sem aprovação. Para aprovar e salvar apenas o mapeamento no registro privado:

```bash
finance-agent ingest private_data/inbox/novo.csv \
  --approve-format "Banco Exemplo" --currency BRL --date-order dmy
```

Importações posteriores com o mesmo schema reconhecem a configuração. Mudanças
em colunas, delimitador, ordem ou largura das linhas geram alertas; ausência de
uma coluna mínima bloqueia o processamento. Veja
[docs/ingestion.md](docs/ingestion.md).

## Etapa 4: persistência SQLite

Inicialize o banco privado e importe uma fixture sintética:

```bash
finance-agent db init
finance-agent ingest samples/synthetic/picpay_demo_jul_ago_2026.csv --persist
finance-agent db summary
```

O terminal exibe somente contagens e códigos seguros. Reimportar o mesmo arquivo
não duplica transações. Coincidências entre arquivos sem identificador bancário
confiável ficam abertas para revisão, em vez de serem descartadas. O lote é
atômico: uma falha reverte todas as linhas financeiras daquela importação.

O banco padrão fica em `private_data/finance_agent.db`, fora do Git. Consulte
[docs/persistence.md](docs/persistence.md).

## Etapa 2: contrato dos dados

Um parser de qualquer banco deve produzir um `TransactionCandidate`. A camada de
validação promove o candidato a `Transaction` somente quando existem:

- data da transação;
- valor não nulo, com sinal/direção sem ambiguidade;
- descrição que identifique o destino ou a origem do dinheiro.

Cartão, conta, método de pagamento, estabelecimento e contraparte são contextos
opcionais. Eles são preservados quando existirem, mas nunca substituem a
descrição. Dados insuficientes viram `PendingTransaction`, com códigos de erro
explícitos, e podem ser corrigidos por `apply_correction`. O futuro canal de
WhatsApp reutilizará essa operação sem carregar regras financeiras no chatbot.

Consulte [docs/canonical-schema.md](docs/canonical-schema.md) e
[docs/data-quality-rules.md](docs/data-quality-rules.md).

## Limites desta etapa

Ainda não foram implementados PDF, OCR, classificação, API, agente ou integração
com WhatsApp. Os parsers atuais cobrem PicPay CSV, Bradesco CSV e CSVs tabulares
aprovados pela pessoa usuária.

## Licenca

MIT. Veja [LICENSE](LICENSE).
