"""Textos exibidos no OpenAPI de runtime (`/docs` e `/openapi.json`)."""

BEARER_SCHEME_NAME = "bearerAuth"

BEARER_SCHEME_DESCRIPTION = (
    "Access token JWT (HS256) emitido por `POST /api/v1/auth/login` ou "
    "`POST /api/v1/auth/refresh`. No botão **Authorize**, informe somente o "
    "token, sem o prefixo `Bearer`."
)

API_DESCRIPTION = """
API Python do SecureBase com autenticação própria e PostgreSQL.

## Autenticação JWT nesta página

> Os valores abaixo são **fictícios**. Não cole senhas reais, tokens de outras
> pessoas, `JWT_SECRET_KEY` ou `SUPABASE_SECRET_KEY` em documentação, issues ou
> capturas de tela. A chave do Supabase **não** é um token de usuário.

**1. Obtenha um token.** Abra `POST /api/v1/auth/login`, clique em
**Try it out** e envie:

```json
{"email": "dev@example.com", "password": "senha-de-exemplo"}
```

Se ainda não houver conta, crie uma antes com `POST /api/v1/auth/register`
(`email`, `password` com 8 a 128 caracteres, `name` e o cabeçalho
`Idempotency-Key`, por exemplo um UUID aleatório). A resposta `200` do login
tem este formato:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<payload>.<assinatura>",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {"id": "…", "email": "dev@example.com", "name": "Dev", "role": "member"},
  "csrf_token": "<valor-csrf>"
}
```

Copie apenas o valor de `access_token`. `expires_in` informa a validade em
segundos (configurada por `JWT_EXPIRY_SECONDS`; padrão de 900 s = 15 min).

**2. Autorize o Swagger.** Clique em **Authorize** (cadeado no topo), cole o
token no campo `Value` do esquema `bearerAuth (http, Bearer)` e confirme em
**Authorize** → **Close**.

- Informe o **token puro**: `eyJhbGciOiJIUzI1NiIs…`.
- **Não** escreva `Bearer eyJ…`: o Swagger já adiciona o prefixo e o
  cabeçalho viraria `Bearer Bearer eyJ…`, recusado com `401`.

**3. Chame uma rota protegida.** Rotas com cadeado exigem o token. Teste com
`GET /api/v1/auth/me` → **Try it out** → **Execute**. O Swagger envia
`Authorization: Bearer <access_token>` e a resposta `200` traz `id`, `email`,
`name` e `role`. Algumas rotas exigem também um perfil específico (por exemplo,
`GET /api/v1/users` exige `master`) e respondem `403 FORBIDDEN` a outros
perfis, mesmo com token válido.

**4. Reconheça token ausente, inválido ou expirado.** Os erros usam
`application/problem+json`:

| Situação | Status | `code` |
|---|---|---|
| Nenhum token informado em **Authorize** | `401` | `AUTHENTICATION_REQUIRED` |
| Token expirado, alterado ou com `Bearer` duplicado | `401` | `INVALID_ACCESS_TOKEN` |
| Sessão encerrada por logout ou troca de senha | `401` | `INVALID_ACCESS_TOKEN` |
| Token válido, mas perfil sem permissão | `403` | `FORBIDDEN` |

Exemplo de resposta para token expirado:

```json
{
  "type": "urn:securebase:problem:invalid_access_token",
  "title": "Não autenticado",
  "status": 401,
  "detail": "A sessão é inválida ou expirou.",
  "instance": "/api/v1/auth/me",
  "code": "INVALID_ACCESS_TOKEN",
  "traceId": "3f1c…"
}
```

**5. Renove o token.** Faça login novamente, ou chame
`POST /api/v1/auth/refresh` informando em `X-CSRF-Token` o `csrf_token` do
login. O cookie de refresh é `HttpOnly` e o navegador o envia automaticamente
quando o login foi feito nesta mesma página. Depois, em **Authorize**, clique
em **Logout** e cole o novo `access_token`. O token informado no Swagger é
descartado ao recarregar a página.

Fora do navegador, o mesmo fluxo com `curl`:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"email":"dev@example.com","password":"senha-de-exemplo"}'

curl http://localhost:8000/api/v1/auth/me \\
  -H "Authorization: Bearer <access_token>"
```

## Erros

Erros usam `application/problem+json` (RFC 9457), com as extensões `code` e
`traceId`; erros de validação incluem também `fields`.
""".strip()
