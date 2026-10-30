# SecureBase Backend

API Python/FastAPI com autenticação própria e contas no PostgreSQL do Supabase.
O Supabase Auth não é usado. A API valida hashes scrypt e emite JWTs HS256 sem
confirmar o e-mail nem depender de SMTP.

## Organização do código

O código da API fica em `src/` e é dividido por responsabilidade:

- **`app/` e `config/`** montam a aplicação FastAPI e validam as configurações
  do ambiente.
- **`modules/auth/`** autentica usuários e verifica permissões; **`routes/`**
  define os endpoints HTTP e **`controller/`** encaminha as requisições para
  os casos de uso.
- **`modules/service/`** implementa as regras de negócio; **`repository/`**
  concentra o acesso ao PostgreSQL por Supabase/PostgREST; **`schemas/`**
  valida e documenta os contratos de entrada e saída.
- **`shared/errors/`** padroniza respostas de erro; `middleware.py` adiciona
  identificadores e logs às requisições.
- **`supabase/migrations/`** versiona alterações de banco, **`tests/`** contém
  testes automatizados e **`docs/`** guarda o contrato OpenAPI e decisões
  arquiteturais.

O fluxo normal é: rota valida e autentica a requisição, controller coordena o
caso de uso, service aplica as regras e repository acessa os dados. Consulte
[`INSTRUCOES.md`](./INSTRUCOES.md) para a descrição detalhada de cada pasta e
arquivo, endpoints, configuração e testes.

## Instalar dependências

Instale Python 3.12 ou superior. No PowerShell, a partir da raiz do projeto:

```powershell
Set-Location .\secure_base_back-end
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Configurar e iniciar a API

1. Crie `secure_base_back-end\.env` a partir de `.env.example`, se ainda não
   existir. Se já existir, **mescle as variáveis novas sem sobrescrever as
   credenciais existentes**. A API exige `SUPABASE_URL`,
   `SUPABASE_SECRET_KEY` e `JWT_SECRET_KEY` aleatório com pelo menos 32
   caracteres. Para o banco remoto, use as credenciais do projeto remoto. Para
   Supabase local, inicie o
   [Supabase CLI](https://supabase.com/docs/guides/local-development/cli/getting-started)
   e use os valores exibidos por `supabase status`.

2. Com o terminal ainda dentro de `secure_base_back-end`, inicie a API:

   ```powershell
   $env:PYTHONPATH = "src"
   .\.venv\Scripts\python.exe -m main
   ```

3. Mantenha o terminal aberto enquanto a API estiver em execução. Para
   encerrá-la, pressione `Ctrl+C`.

O servidor local usa `HOST` e `PORT` do `.env` (por padrão,
`http://localhost:8000`). Confira:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`
- Liveness: `http://localhost:8000/health/live`
- Readiness: `http://localhost:8000/health/ready`

Os dois health checks devem responder `200`; readiness exige acesso às tabelas
`securebase_users`, `securebase_homes`, `securebase_home_members`,
`securebase_refresh_sessions` e `securebase_idempotency_keys`. A API lê o
`.env` do backend, não o
`.env.local` do frontend.

No Swagger, use `POST /api/v1/auth/register` com um cabeçalho
`Idempotency-Key` aleatório para criar uma conta e depois `POST
/api/v1/auth/login`; a resposta contém um access JWT válido por 15 minutos e
define cookies HttpOnly para refresh e CSRF. O refresh rotaciona os cookies e
a sessão expira 30 dias após o login. Clique em **Authorize** e informe o
`access_token` para testar as rotas protegidas. A chave de servidor do Supabase
nunca é um bearer token de usuário.

As senhas/contas antigas do Supabase Auth não podem ser migradas. Usuários devem
se cadastrar novamente. Quem cria uma residência autenticado torna-se o
`primary` daquela casa. Desenvolvedores podem receber o papel global `master`
pelo SQL Editor do Supabase. Consulte o
[manual de desenvolvimento](./INSTRUCOES.md) para os comandos e limites dos
papéis.

### Administrador master para desenvolvedores

A migration `20261025000300_master_admin_role.sql` adiciona `master` ao enum de
papéis usado por `securebase_users`; `20261025000400_households.sql` cria as
tabelas de residências e associações. A migration
`20261025000500_auth_sessions_and_idempotency.sql` cria o armazenamento de
refresh sessions, idempotency keys e funções transacionais usadas pelo backend.
Aplique todas as migrations no banco alvo após confirmar o ambiente. A migration
de residências cria uma casa
inicial para cada conta que já tinha papel `primary`, transfere esse papel para
a casa e converte o papel global antigo em `member`; não presume quais membros
antigos pertencem a essas casas.

Depois que a conta do desenvolvedor tiver sido criada e sua identidade
confirmada por um canal confiável, atribua o papel manualmente pelo SQL Editor:

```sql
update public.securebase_users
set role = 'master', updated_at = now()
where lower(email) = lower('dev-verificado@example.com')
returning id, email, role;
```

Confirme que a consulta retorna exatamente uma conta. `master` pode gerenciar
contas e residências globalmente, mas não pode remover a si mesmo nem outras
contas `master`. Também não pode excluir uma conta que ainda seja titular de
uma residência; transfira a propriedade antes. A promoção não está disponível
pela API.

As configurações do frontend estão em `secure_base_front-end/.env.example`.
Consulte [INSTRUCOES.md](./INSTRUCOES.md) para integração, migrações, papéis,
testes e limitações.
