# ADR 0004 — Erros da API com Problem Details (RFC 9457)

- **Status:** Aceita.
- **Data:** 2026-11-05.

## Contexto

Rotas e serviços precisam comunicar erros de negócio, validação, HTTP e falhas
inesperadas. Sem um formato comum, cada parte poderia devolver respostas
diferentes, obrigando os clientes a tratar formatos e mensagens específicos.
Também é necessário correlacionar uma resposta de erro com os logs do servidor
sem expor detalhes internos da aplicação.

O backend mantém funcionalidades compartilhadas em `src/shared/`. O tratamento
central de erros fica em `src/shared/errors/problem_details.py`; a configuração
dos handlers e a documentação OpenAPI ficam em `src/app/factory.py`.

## Decisões

- Representar os erros da API com `application/problem+json`, seguindo o padrão
  HTTP Problem Details da RFC 9457.
- Centralizar o formato, a exceção de domínio `Problem` e os handlers em
  `shared/errors/problem_details.py`, para que rotas e serviços compartilhem o
  mesmo contrato em vez de montar respostas de erro individualmente.
- Incluir os campos padrão `type`, `title`, `status`, `detail` e `instance`.
  Acrescentar `code` como identificador estável do erro e `traceId` para
  correlação com a requisição. Erros de validação podem incluir `fields` com os
  campos inválidos.
- Fazer serviços e outras partes da aplicação lançarem `Problem` com status
  HTTP, código, título e detalhe adequados às falhas esperadas, como conflitos
  de regra de negócio.
- Tratar centralmente erros `Problem`, erros de validação do FastAPI, exceções
  HTTP do framework e erros inesperados. Respostas de erro inesperado não
  expõem detalhes internos; a falha é registrada no servidor com o identificador
  da requisição quando disponível.
- Documentar o schema `Problem` e as respostas de erro no OpenAPI do runtime.

## Alternativas consideradas

- **Cada rota criar seu próprio formato de erro:** rejeitada, pois causa
  inconsistência e aumenta o acoplamento dos clientes aos detalhes de cada
  endpoint.
- **Usar somente mensagens de texto ou o formato padrão de erro do framework:**
  rejeitada, pois não oferece um contrato uniforme com código estável e
  identificador de correlação para o cliente.
- **Expor detalhes e exceções internas ao cliente:** rejeitada, pois pode revelar
  informações de implementação e infraestrutura. Os detalhes completos devem
  permanecer nos logs do servidor.

## Consequências

- Clientes podem interpretar erros pelo status HTTP e pelo `code`, sem depender
  exclusivamente do texto localizado em `title` ou `detail`.
- O `traceId` permite correlacionar a falha observada pelo cliente com os logs
  do servidor.
- Novos erros de negócio devem usar códigos estáveis e respostas compatíveis
  com o schema compartilhado; mudanças nesse contrato precisam ser refletidas
  na documentação OpenAPI.
- A RFC define o formato base; `code`, `traceId` e `fields` são extensões do
  contrato SecureBase.
- Esta decisão detalha e complementa a decisão de erros HTTP registrada na
  [ADR 0002](./0002-sessoes-idempotencia-e-erros-http.md).
