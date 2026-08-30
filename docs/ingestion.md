# Etapa 3: ingestão e formatos extensíveis

## Escopo implementado

- perfil de CSV por conteúdo;
- detecção de PicPay e Bradesco sem usar o nome do arquivo;
- parser especializado para cada formato conhecido;
- sugestão de mapeamento para CSV desconhecido;
- registro local de mapeamentos aprovados;
- detecção de mudança de schema;
- duplicidade dentro do lote;
- relatório seguro e CLI em modo sem persistência.

PDF textual e OCR continuam fora desta etapa.

## Fluxo

```text
CSV
 |
 v
SchemaProfiler
 |
 v
FormatDetector <---- formatos aprovados em private_data/
 |
 +---- conhecido ------> SchemaDriftDetector ----> parser específico
 |
 +---- genérico -------> sugestão ----> confirmação ----> GenericCsvParser
 |
 +---- desconhecido ---> bloqueio seguro
                                      |
                                      v
                             TransactionCandidate
                                      |
                                      v
                       validação canônica da Etapa 2
                            |                    |
                            v                    v
                       Transaction       PendingTransaction
```

## Aprendizado de formato

O aprendizado não usa ML. `MappingRegistry` grava apenas:

- assinatura do schema;
- delimitador;
- nomes normalizados das colunas;
- correspondência entre colunas e campos canônicos;
- nome fornecido para o formato.
- moeda ISO aprovada;
- ordem da data, quando informada (`dmy`, `mdy` ou `ymd`).

O registro padrão é `private_data/config/bank_mappings.json`, ignorado pelo Git.
Valores, descrições e linhas do extrato não são gravados no registro.

Sem `--approve-format`, uma sugestão nunca é executada automaticamente. A moeda
é obrigatória na aprovação, impedindo que um extrato internacional seja
silenciosamente marcado como BRL. Se a ordem da data não for informada, datas
como `03/04/2026` permanecem pendentes por ambiguidade.

## Schema drift

São detectados:

- coluna conhecida ausente;
- coluna nova;
- mudança de delimitador;
- mudança na ordem;
- linhas com largura diferente do cabeçalho.

Ausência de data, descrição ou representação de valor é bloqueante. Mudanças não
bloqueantes são relatadas e o mapeamento por nome continua sendo usado.

## Contabilidade de registros

Toda linha de dados precisa terminar em exatamente um estado:

- transação válida;
- pendência;
- duplicidade;
- registro não transacional/rejeitado.

O modelo `IngestionSummary` rejeita resultados cujas contagens não fechem com o
total lido.

## Logs e saída

`safe_summary_lines` e `--json` incluem somente:

- status e formato;
- instituição;
- contagens;
- códigos de alerta;
- nomes de colunas em uma sugestão de mapeamento.

Não exibem linhas, descrições, valores, contas, hashes ou transações.

## Limites conhecidos

- duplicidade é detectada apenas dentro do arquivo atual;
- formato aprendido depende de cabeçalhos suficientemente estáveis;
- inferência de entrada/saída é conservadora; direção ambígua vira pendência;
- CSVs com estrutura irregular desconhecida são rejeitados, não corrigidos por
  heurística;
- o limite padrão por CSV é 10 MiB para evitar leitura ilimitada em memória.
