# ADR 0002 — Sessões, idempotência e erros HTTP

- **Status:** Aceita.
- **Data:** 2026-10-25.

## Contexto

A API passou a controlar diretamente o ciclo de autenticação. Um access token
curto não basta para manter uma sessão utilizável, e retries de operações que
criam dados podem duplicar recursos. O contrato também precisa representar
falhas de negócio, validação, framework e dependências indisponíveis de forma
consistente.

## Decisões

- Emitir access JWT HS256 com duração de 15 minutos e refresh token opaco em
  cookie `HttpOnly`, com expiração absoluta de 30 dias.
- Armazenar somente SHA-256 do refresh token. Rotacionar o token a cada refresh,
  vincular a sessão a uma família e à versão de autenticação da conta e revogar
  a família no logout ou após alteração de senha.
- Exigir `Idempotency-Key` em cadastro, criação de residência e associação de
  membro. Manter fingerprint do payload e resposta concluída por 24 horas;
  mesma chave com payload diferente ou operação concorrente responde `409`.
- Usar `PATCH` para alteração de senha e transferência de titularidade.
- Retornar erros no formato `application/problem+json`, baseado em RFC 9457,
  com `code` estável e `traceId`. Erros de validação, exceções HTTP do framework,
  erros de domínio e falhas inesperadas passam pelo tratamento central.
- Documentar no OpenAPI de runtime e em `docs/api.yml` que respostas de erro
  seguem o schema `Problem`, incluindo respostas padrão e validação `422`.
- Identificar indisponibilidade do banco no readiness como `503` com código
  `DATABASE_UNAVAILABLE`.

## Consequências

- O cliente precisa preservar o cookie de refresh e enviar o CSRF em refresh e
  logout; o access token continua sendo enviado como bearer.
- Logout e alteração de senha invalidam access tokens associados à família,
  além de impedir novos refreshes.
- Replays idempotentes não duplicam a operação; como reserva, mutação e cache
  da resposta ainda não são uma única transação, uma falha entre essas etapas
  pode deixar a chave em andamento até sua expiração.
- Erros internos não expõem stack trace nem mensagens privadas do banco; o
  `traceId` permite correlacionar o problema com os logs do servidor.
