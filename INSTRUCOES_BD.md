# Banco de dados local

O backend usa PostgreSQL no Supabase e acessa tabelas e funções por
HTTPX/PostgREST. O login da aplicação é próprio do SecureBase; o Supabase Auth
local não participa desse fluxo.

## Requisitos e isolamento

Para desenvolvimento, instale Docker Desktop com WSL 2 e a Supabase CLI. O
projeto local é definido por [`supabase/config.toml`](./supabase/config.toml)
e não compartilha banco, dados ou credenciais com ambientes hospedados.

Use sempre o Supabase local durante o desenvolvimento. Nunca copie credenciais
de produção para `.env`, logs, issues ou pull requests. `supabase status` exibe
credenciais geradas localmente; mantenha essa saída privada.

## Iniciar o ambiente

Execute no PowerShell, a partir da raiz do backend:

```powershell
supabase start
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Preencha `.env` usando a URL REST e a chave local indicadas pela CLI. Gere um
`JWT_SECRET_KEY` aleatório com pelo menos 32 caracteres, diferente da chave
Supabase. Configure também a origem local do frontend em `CORS_ORIGINS`.
Consulte [`README.md`](./README.md) para iniciar a API.

## Criar e validar migrations

Toda alteração estrutural — tabelas, colunas, funções, constraints, permissões
ou RLS — deve ser registrada em uma migration SQL nova em
`supabase/migrations/`, revisada e versionada no Git.

```powershell
supabase migration new descricao_da_alteracao
supabase migration up --local
supabase db lint --local --fail-on error
```

`migration up --local` aplica somente migrations pendentes no banco local.
Depois, execute os testes do backend e valide os fluxos afetados. Migrations
que já podem ter sido aplicadas em qualquer ambiente não devem ser editadas ou
removidas; correções devem ser migrations novas e ordenadas.

Não execute comandos de migração sem confirmar o destino. Para este fluxo,
use apenas comandos explicitamente locais. Não use `supabase link`,
`supabase db push`, `supabase db reset` ou `supabase migration repair`.

## Produção e segurança

Produção deve usar projeto e credenciais próprios, separados do ambiente local.
Alterar schema diretamente em produção não é procedimento normal: mudanças
devem passar por revisão, teste local e aprovação explícita.

O deploy está desabilitado. Antes de habilitá-lo, é necessário identificar os
provedores de hospedagem, verificar e regularizar manualmente o histórico
remoto de migrations e restringir credenciais ao GitHub Environment
`production`, com aprovação manual. Não tente regularizar o histórico
remotamente de forma automática. Branches e pull requests não podem acessar
secrets de produção.
