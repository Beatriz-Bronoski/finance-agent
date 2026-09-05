# Etapa 4: persistência SQLite

Esta etapa grava somente resultados que concluíram a ingestão e mantém tentativas
bloqueadas sem criar linhas financeiras. O banco padrão é
`private_data/finance_agent.db`, ignorado pelo Git.

## Estrutura

- `schema_migrations`: versões aplicadas ao banco;
- `import_runs`: histórico e contagens de cada tentativa;
- `transactions`: transações canônicas válidas;
- `pending_transactions`: registros que exigem correção humana;
- `duplicate_candidates`: coincidências entre arquivos e sua estratégia de detecção.
- `categories`: categorias configuráveis e seu estado;
- `classification_rules`: regras privadas ordenadas por prioridade;
- `classification_decisions`: decisão atual e histórico substituído;
- `classification_reviews`: itens que exigem confirmação;
- `classification_corrections`: auditoria das correções humanas.

Dinheiro é armazenado como `INTEGER` na menor unidade da moeda. Assim, `R$ 42,90`
é persistido como `4290` com moeda `BRL`, sem conversão para ponto flutuante.

## Inicialização

No PowerShell do VS Code:

```powershell
python -m finance_agent db init
```

As migrações são idempotentes: a segunda execução não recria tabelas nem perde
dados.

## Execução visível

```powershell
python -m finance_agent ingest `
    '.\samples\synthetic\picpay_demo_jul_ago_2026.csv' `
    --persist
```

Saída segura esperada na primeira execução:

```text
Status: completed_with_issues
Detecção: known
Formato: picpay_csv_v1
Instituição: PicPay
Registros lidos: 12
Transações válidas: 11
Pendências: 0
Duplicidades: 1
Registros rejeitados: 0
Alertas: duplicate_record=1
---
Persistência: stored
Transações gravadas nesta execução: 11
Pendências gravadas nesta execução: 0
Duplicidades entre arquivos: 0
Total de importações concluídas: 1
Total de transações no banco: 11
Total de pendências abertas: 0
Candidatas a duplicidade: 0
Versão do banco: 2
```

Executar o mesmo arquivo novamente retorna `already_imported` e não aumenta o
total de transações.

## Deduplicação conservadora

1. Hash igual do arquivo: a importação inteira é idempotente.
2. ID externo confiável, instituição, data, valor e moeda iguais: duplicidade
   confirmada e auditada.
3. Sem ID confiável, data, valor, moeda e descrição iguais: candidata aberta
   para revisão; o sistema não apaga a ocorrência silenciosamente.
4. IDs vazios ou compostos somente por zeros não são tratados como confiáveis.

## Atomicidade

Transações, pendências, duplicidades e contagens são escritas na mesma transação
SQLite. Se qualquer inserção falhar, todas as linhas financeiras do lote são
revertidas. A tentativa pode então ser registrada separadamente com um código de
erro seguro.

## Resumo do banco

```powershell
python -m finance_agent db summary
```

O comando mostra somente contagens. Descrições, valores e identificadores não
são impressos.

## Segurança

- Não mova o banco para `samples/` ou outra pasta versionada.
- Nunca adicione `private_data/` ao Git com `--force`.
- O SQLite não criptografa o arquivo; use a criptografia de dispositivo do
  Windows para dados reais.
- Use somente extratos sintéticos em demonstrações, testes e vídeos.
