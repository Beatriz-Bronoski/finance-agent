# Regras de qualidade e alertas

## Princípio

Nenhuma linha incompleta é descartada silenciosamente. Um candidato com problema
bloqueante vira `PendingTransaction`, preservando sua origem e os códigos que
explicam o que precisa ser corrigido.

## Bloqueios implementados

| Código | Condição | Correção esperada |
|---|---|---|
| `missing_transaction_date` | Data ausente. | Informar a data. |
| `invalid_transaction_date` | Parser encontrou uma data ilegível. | Confirmar a data correta. |
| `missing_amount` | Valor ausente. | Informar o valor. |
| `invalid_amount` | Parser não conseguiu converter o valor. | Confirmar o valor. |
| `zero_amount` | Valor igual a zero. | Corrigir ou descartar o registro. |
| `ambiguous_amount_direction` | Valor positivo sem entrada/saída. | Informar a direção. |
| `conflicting_amount_direction` | Sinal incompatível com a direção. | Corrigir valor ou direção. |
| `missing_description` | Descrição ausente ou vazia. | Informar destino/origem. |
| `generic_description_only` | Texto contém somente termos como cartão, Visa, compra ou PIX. | Informar destino/origem real. |

Descrições como `CARTÃO VISA` são bloqueadas. `MERCADO AURORA CARTÃO` é aceita,
porque identifica o estabelecimento e mantém o meio de pagamento como contexto.

## Correções

`CandidateCorrection` permite alterar data, valor, direção e descrição. Depois de
cada correção, `apply_correction` executa todas as regras novamente. Se ainda
faltar informação, uma nova pendência é retornada; se estiver completa, uma
`Transaction` é criada.

A aplicação que persistir os resultados deve marcar a pendência anterior como
`corrected` somente quando a promoção para `Transaction` for bem-sucedida.

## Segurança

Mensagens de qualidade são fixas e não repetem nomes, descrições, valores,
contas, hashes ou conteúdo bruto. Logs futuros devem registrar somente o código
do problema, IDs internos, contagens e duração.

## Fora do escopo desta etapa

Os códigos `duplicate_candidate` e `unsupported_record` já fazem parte do
vocabulário, mas serão produzidos por deduplicação e parsers em etapas futuras.
