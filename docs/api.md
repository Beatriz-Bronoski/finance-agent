# API local do MVP

A etapa 6 expõe as operações já existentes das etapas anteriores por HTTP. A API
não recria regras de negócio: ela valida a entrada com Pydantic e chama o motor e
os repositórios da etapa 5.

## Executar

Após instalar o projeto com as dependências de desenvolvimento:

```bash
python -m uvicorn finance_agent.api.aplicacao:aplicacao --reload --host 127.0.0.1
```

A documentação interativa fica em `http://127.0.0.1:8000/docs` e a verificação
de saúde em `http://127.0.0.1:8000/saude`.

## Operações

| Método | Caminho | Finalidade |
|---|---|---|
| GET | `/saude` | Verificar se a API está disponível |
| GET/POST | `/categorias` | Listar ou criar categorias |
| PATCH | `/categorias/{id_categoria}` | Ativar ou desativar uma categoria |
| GET | `/regras` | Listar regras sem revelar os critérios financeiros |
| PATCH | `/regras/{id_regra}` | Ativar ou desativar uma regra |
| POST | `/classificacoes/executar` | Classificar transações ainda sem decisão |
| GET | `/classificacoes/resumo` | Consultar apenas contagens operacionais |
| GET | `/revisoes/pendentes` | Consultar a fila sem descrições ou valores |
| POST | `/transacoes/{id_transacao}/corrigir` | Confirmar uma classificação |

## Limites intencionais do MVP

- um único usuário;
- execução local em `127.0.0.1`;
- sem autenticação, permissões ou contas;
- importação de extratos continua no terminal;
- banco SQLite privado permanece fora do Git;
- respostas de revisão não incluem descrição, valor ou dados bancários.

Não exponha a aplicação na rede com `--host 0.0.0.0` enquanto autenticação e
proteções de produção não forem implementadas.
