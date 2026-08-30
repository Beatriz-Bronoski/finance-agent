# Qualidade contínua entre etapas

## Regra do projeto

Cada etapa deve provar que o código novo está conectado ao fluxo real e que
caminhos de falha são seguros. Uma função criada para uso futuro não deve ficar
silenciosamente esquecida: deve ser integrada, testada ou removida do escopo
atual.

## Verificações automatizadas atuais

- teste arquitetural que encontra funções públicas sem chamada no código ou nos
  testes;
- invariantes de contagem nos resultados de parser e ingestão;
- compilação de todos os módulos;
- testes de privacidade que bloqueiam artefatos financeiros reais;
- teste que impede dependência direta de Azure, Google, Twilio ou WhatsApp no
  núcleo de ingestão;
- testes de formatos conhecidos, desconhecidos, aprendidos e alterados;
- testes de valores inválidos, datas inválidas, duplicidade e registro de saldo;
- teste de que a saída da CLI não contém descrições nem valores.

## Checklist para as próximas etapas

1. Executar toda a suíte, não apenas os testes novos.
2. Confirmar que toda função pública possui chamada real ou teste de contrato.
3. Exercitar sucesso, ausência, valor inválido, ambiguidade e repetição.
4. Conferir se contagens de entrada e saída fecham.
5. Testar falha de arquivo, configuração e dependência externa.
6. Revisar logs para impedir exposição de conteúdo financeiro.
7. Procurar funções temporárias, `TODO`, `FIXME` e caminhos não implementados.
8. Compilar os módulos e executar a interface da pessoa usuária.
9. Manter integrações externas atrás de adaptadores.
10. Documentar limitações que ainda não possuem solução.

Essas verificações reduzem risco, mas não significam ausência absoluta de bugs.
Cada novo formato real deverá ser validado com contagens e amostras privadas fora
do Git antes de ser considerado confiável.
