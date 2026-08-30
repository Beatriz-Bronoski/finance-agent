# Privacidade e uso de dados

## Modos de execucao

### Privado

- Processa extratos reais apenas na maquina da pessoa usuaria.
- Usa diretorio ignorado pelo Git.
- Nao envia PDF completo, conta, nome ou saldo para modelos externos.

### Demonstracao

- Usa exclusivamente dados sinteticos.
- Pode ser implantado no Azure ou em outro provedor.
- Nao aceita upload de extratos reais enquanto o ambiente for publico.

## Minimizacao para classificacao por IA

Quando a classificacao por IA for implementada, o modelo devera receber apenas:

- descricao normalizada e minimizada;
- tipo da transacao;
- moeda;
- categorias permitidas;
- regras relevantes.

Identificadores, saldo, nome, conta e documento bruto ficam fora do prompt.

## Requisitos de logs

Logs nao podem registrar conteudo bruto de linhas, descricoes completas, payloads de modelos ou credenciais. Devem usar IDs internos, contagens, duracoes e codigos de erro.

## Dados sinteticos

Os exemplos publicos nao sao copias mascaradas. Foram criados do zero e preservam somente caracteristicas tecnicas necessarias para testar delimitadores, sinais, IDs, duplicidades e segmentacao.
