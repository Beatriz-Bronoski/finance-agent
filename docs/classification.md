# Etapa 5: classificação determinística e correção humana

A classificação separa **natureza** e **categoria**. As naturezas permitidas são:

- `despesa`;
- `receita`;
- `transferencia_interna`;
- `estorno`.

Despesas e receitas exigem uma categoria ativa. Transferências internas e
estornos podem ficar sem categoria. Uma transferência interna não deve ser
somada como despesa ou receita nos relatórios futuros.

## Ordem e conflitos

As regras usam prioridades de 1 a 1000. Somente as regras correspondentes com a
maior prioridade participam da decisão:

1. se não houver regra, a transação fica em revisão;
2. se uma regra tiver a maior prioridade, seu resultado é aplicado;
3. se várias regras empatarem e concordarem, o resultado comum é aplicado;
4. se empatarem e discordarem, nenhuma vence e o conflito fica em revisão;
5. uma decisão manual atual nunca é reclassificada silenciosamente por uma nova regra.

O padrão de uma regra lembrada pela usuária é prioridade 800 e correspondência
exata pela descrição normalizada mais a instituição. Critérios e descrições
permanecem no SQLite privado e não aparecem nos resumos do terminal.

## Execução local

Depois de importar uma fixture sintética:

```powershell
python -m finance_agent categories add 'Alimentação'
python -m finance_agent classify run
python -m finance_agent classify pending
python -m finance_agent classify summary
```

`classify pending` mostra somente o UUID interno, o motivo e a quantidade de
regras candidatas. Para corrigir uma transação e lembrar a escolha:

```powershell
python -m finance_agent classify correct <UUID_DA_TRANSACAO> `
    --nature despesa `
    --category 'Alimentação' `
    --remember
```

Sem `--remember`, a correção vale somente para aquela transação. Com
`--remember`, lançamentos futuros equivalentes podem ser classificados. Os já
classificados não são alterados; uma revisão histórica exigirá uma ação futura
explícita.

## Administração segura

```powershell
python -m finance_agent categories list
python -m finance_agent categories disable <UUID_DA_CATEGORIA>
python -m finance_agent rules list
python -m finance_agent rules disable <UUID_DA_REGRA>
```

Desativar uma categoria também impede que suas regras sejam usadas, sem apagar
o histórico. `rules list` informa prioridade, saída e quantidade de critérios,
mas nunca imprime as descrições que acionam a regra.

## Auditoria

O banco mantém:

- decisão atual e decisões substituídas;
- origem da decisão (`rule` ou `user`);
- regra vencedora e IDs das regras empatadas;
- revisões abertas e resolvidas;
- correções e a eventual regra criada por `--remember`.

Ainda não existe machine learning nesta etapa. As correções confirmadas formam
uma base rotulada e auditável para avaliar um modelo posteriormente.
