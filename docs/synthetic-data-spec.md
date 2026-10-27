# Especificacao das fixtures sinteticas

## PicPay

O CSV sintetico preserva:

- seis colunas e delimitador por virgula;
- encoding UTF-8;
- datas ISO;
- valores no formato brasileiro;
- prefixos de credito e debito;
- sinal de menos Unicode `U+2212`;
- uma linha duplicada intencional para testar importacoes sobrepostas.

## Bradesco CSV

O CSV sintetico preserva:

- delimitador por ponto e virgula;
- linhas de cabecalho que nao comecam por data;
- campos monetarios brasileiros;
- ID zero;
- IDs menores, iguais e maiores que sete digitos;
- historico com ponto e virgula adicional.

## Regra de ouro

Fixtures devem reproduzir formatos e falhas estruturais, nunca valores ou identidades das fontes privadas.

