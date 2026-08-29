# Politica de seguranca

## Dados proibidos no repositorio

- Extratos bancarios reais ou parcialmente anonimizados.
- Nome, CPF, telefone, e-mail, agencia, conta ou identificadores reais.
- Chaves de API, tokens, senhas ou arquivos `.env`.
- Bancos SQLite com transacoes pessoais.
- Notebooks com saidas de execucao ou tabelas reais.

## Processamento privado

Dados reais devem permanecer em `private_data/` e ser processados localmente. Demonstracoes e testes em nuvem devem usar exclusivamente os arquivos de `samples/synthetic/`.

## Incidente

Se um dado sensivel for versionado:

1. Interrompa novos pushes.
2. Revogue imediatamente qualquer credencial exposta.
3. Remova o dado de todo o historico Git, nao apenas do commit mais recente.
4. Invalide caches e artefatos de CI relacionados.
5. Registre o incidente sem reproduzir o dado sensivel.

Nao abra uma issue publica contendo o dado exposto.

