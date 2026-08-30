# Schema canônico de transações

## Objetivo

Receber formatos diferentes sem criar uma tabela específica para cada banco. Os
parsers apenas traduzem suas fontes para `TransactionCandidate`; as mesmas regras
de domínio validam todos os candidatos.

## Fluxo da Etapa 2

```text
arquivo ou API
      |
      v
parser específico da fonte
      |
      v
TransactionCandidate
      |
      v
validate_candidate
   |             |
   v             v
Transaction   PendingTransaction
                    |
                    v
          correção humana (canal neutro)
                    |
                    v
             apply_correction
```

O WhatsApp será um canal futuro sobre `apply_correction`. Ele coleta uma resposta
da pessoa, monta `CandidateCorrection` e chama o caso de uso. A lógica de
validação não ficará acoplada ao WhatsApp.

## Campos mínimos

| Campo | Regra |
|---|---|
| `transaction_date` | Data em que a transação ocorreu. |
| `amount_minor` | Inteiro na menor unidade da moeda; em BRL, centavos. Saídas negativas e entradas positivas. |
| `description_raw` | Destino ou origem do dinheiro, como estabelecimento, pessoa, conta, produto ou serviço. |

`currency` acompanha o valor no padrão ISO de três letras. Formatos conhecidos
definem a moeda; formatos novos exigem confirmação durante a aprovação.

Um valor positivo sem `amount_direction` é pendente, pois o formato da fonte pode
representar débitos e créditos como números positivos. Um valor negativo já pode
ser interpretado como saída.

## Contexto opcional

- hora;
- instituição de origem;
- método e instrumento de pagamento;
- apelido e últimos quatro dígitos do cartão;
- estabelecimento ou contraparte;
- saldo;
- identificador externo e referência interna da conta;
- metadados específicos da fonte.

Ausência desses campos não impede a transação. Cartão e método de pagamento não
são descrição.

## Rastreabilidade

Cada candidato contém `source_record_hash` e `SourceLocation`. Esses campos
permitem investigar uma falha sem registrar conteúdo financeiro bruto em logs.
O nome original do arquivo não faz parte de `SourceLocation`.

## Contexto para classificação

`ClassificationContext` cria uma visão reduzida da transação. Ela inclui os três
campos mínimos e somente o contexto opcional útil disponível. Exclui metadados
privados, referência de conta, identificador externo, saldo, hash e localização
no arquivo.

## Responsabilidades futuras

- O parser reconhece colunas, datas, moedas e sinais da fonte.
- Esta camada decide se o dado canônico é válido ou pendente.
- A persistência salva transações e pendências sem alterar regras.
- O WhatsApp coleta correções; não interpreta extratos.
- O classificador recebe apenas `ClassificationContext`.
