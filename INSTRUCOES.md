# Manual de desenvolvimento do backend SecureBase

Este manual descreve a primeira etapa do backend. O backend é Python/FastAPI e
usa autenticação própria com contas armazenadas no PostgreSQL do Supabase. O frontend foi analisado antes da definição dos
contratos: não havia endpoints HTTP; autenticação e usuários eram mantidos
somente no navegador. A integração substitui esse armazenamento local por
contas próprias e perfis autorizados no servidor.

## 1. Escopo e estado

### Implementado nesta etapa

- API versionada `/api/v1`.
- Health checks público de processo e de dependências.
- Perfil global `master` e perfis de residência `primary` e `member`.
- Autorização por ação em `src/modules/auth/middleware.py`.
- Cadastro e login próprios em `POST /api/v1/auth/register` e
  `POST /api/v1/auth/login`, com hash scrypt e JWT da API, sem SMTP ou
  confirmação de e-mail.
- Access tokens de 15 minutos e refresh token rotativo em cookie `HttpOnly`;
  a sessão expira até 30 dias após o login e é revogada no logout/alteração de senha.
- Idempotência obrigatória nas operações de criação, com replay de resposta por 24 horas.
- Sessão e gestão de contas validadas contra `securebase_users` no PostgreSQL.
- `master` é global; `primary` e `member` são papéis por residência, com
  `member` como padrão seguro.
- Cada usuário pode pertencer a várias residências; o criador é o `primary`
  daquela casa e administra somente os membros associados a ela.
- `master` administra globalmente e pode transferir a titularidade das casas.
- Respostas de erro RFC 9457, validação de entrada, CORS restrito e identificador
  de requisição.
- Migrações versionadas de contas, residências, associações de membros e RLS.
- Testes de contrato e de autorização, além de CI para o backend.

### Ainda pendente

Dispositivos, sensores, leituras, alertas, eventos, auditoria persistente,
observabilidade de produção, deploy e testes end-to-end
com Supabase real. Esses recursos não são expostos pelo simulador atualmente e
não foram inventados nesta etapa.

## 2. Decisões técnicas

- **Python 3.12+ e FastAPI:** tipagem e geração automática de OpenAPI.
- **Autenticação própria:** o backend verifica senhas com scrypt e emite JWT
  HS256 assinados com `JWT_SECRET_KEY`. O Supabase Auth não é usado.
- **PostgreSQL do Supabase:** contas e papéis ficam em `securebase_users`;
  PostgREST é usado somente como acesso ao banco. O Supabase CLI é recomendado
  para ambientes locais.
- **Camadas:** rotas HTTP, dependências de autenticação/autorização e gateway de
  integração Supabase ficam separados. A hierarquia de papéis e a autorização
  por ação ficam no backend, não no navegador.
- **Erros:** `application/problem+json` segue RFC 9457 e inclui código estável,
  rota e `traceId`.

O detalhamento está em [ADR 0001](./docs/adr/0001-python-fastapi-supabase.md).
A renovação de sessão, idempotência e contrato de erros estão em
[ADR 0002](./docs/adr/0002-sessoes-idempotencia-e-erros-http.md).

## 3. Estrutura

```text
secure_base_back-end/
├── src/
│   ├── app/               # Criação da aplicação e configuração de logs
│   ├── config/            # Configurações carregadas do ambiente
│   ├── modules/           # Funcionalidades organizadas em camadas
│   │   ├── auth/          # Autenticação, dependências e autorização
│   │   ├── controller/   # Coordenação entre rotas e serviços
│   │   ├── repository/   # Acesso ao PostgreSQL via Supabase/PostgREST
│   │   ├── routes/       # Endpoints HTTP da API
│   │   ├── schemas/      # Contratos, validação e respostas Pydantic
│   │   └── service/      # Regras de negócio e operações da aplicação
│   ├── shared/errors/     # Erros padronizados no formato RFC 9457
│   ├── main.py            # Ponto de entrada da aplicação ASGI
│   └── middleware.py      # ID de requisição e log de conclusão HTTP
├── supabase/
│   ├── config.toml        # Configuração do Supabase local
│   └── migrations/        # Migrações SQL versionadas
├── tests/                 # Testes automatizados da API
├── docs/
│   ├── adr/               # Decisões arquiteturais
│   └── api.yml            # Contrato OpenAPI versionado
├── .env.example           # Modelo de configuração sem credenciais reais
├── Dockerfile
├── package.json           # Dependências JavaScript auxiliares do projeto
└── INSTRUCOES.md
```

### Responsabilidade de cada pasta e arquivo

#### Aplicação e configuração

- **`src/main.py`** cria a aplicação e, quando executado diretamente, inicia o
  servidor Uvicorn usando host, porta e ambiente configurados.
- **`src/app/factory.py`** monta a aplicação FastAPI: configura CORS, registra
  o middleware e os tratadores de erro, inclui as rotas e gera o OpenAPI com o
  formato de erro `Problem`.
- **`src/app/logging.py`** disponibiliza o logger usado para registrar eventos
  de requisição e falhas inesperadas.
- **`src/config/settings.py`** define as configurações vindas do `.env` ou do
  ambiente, valida valores como prefixo, origens CORS e requisitos de TLS, e
  fornece a instância reutilizável de configurações.
- **`src/middleware.py`** atribui um identificador único a cada requisição,
  devolve-o no header `X-Request-ID` e registra método, caminho, status e
  duração, sem registrar credenciais ou corpos.

#### `src/modules/auth/` — autenticação e autorização

Essa pasta trata de **quem está fazendo a requisição** e **o que essa pessoa
pode fazer**. Ela é diferente de `src/modules/service/`, que contém regras e
operações de negócio.

- **`dependencies.py`** fornece dependências FastAPI para criar o repositório,
  exigir um bearer token válido e disponibilizar o usuário autenticado.
- **`middleware.py`** define verificações reutilizáveis de permissão: acesso
  exclusivo de `master` ou acesso de `primary` à própria residência (com
  `master` também autorizado).
- **`security.py`** implementa hash e verificação de senhas com scrypt,
  emissão e validação de access JWTs, criação de refresh tokens e hash dos
  refresh tokens.

#### `src/modules/routes/` — endpoints HTTP

As rotas recebem a requisição, aplicam dependências de autenticação/autorização,
validam entradas com schemas, chamam controllers e definem status e formato das
respostas. Não devem concentrar regras de negócio nem chamadas diretas ao banco.

- **`auth_routes.py`** expõe cadastro, login, renovação e encerramento de
  sessão, consulta do perfil e alteração de senha. Também configura cookies de
  sessão, proteção CSRF e idempotência no cadastro.
- **`health_routes.py`** expõe os endpoints públicos `/health/live` e
  `/health/ready`.
- **`homes_routes.py`** expõe criação e consulta de residências, gestão de
  membros e transferência de titularidade, aplicando as permissões adequadas.
- **`users_routes.py`** expõe consulta e remoção global de contas, restritas a
  `master`.
- **`routes.py`** reúne os routers: health fica fora do prefixo versionado; as
  demais rotas ficam sob o prefixo configurado, normalmente `/api/v1`.

#### `src/modules/controller/` — coordenação dos casos de uso

Os controllers fazem a ponte entre endpoints e serviços. Recebem dados já
validados, chamam a operação correspondente e retornam seu resultado, mantendo
as rotas mais simples e sem repetir regras de negócio.

- **`auth_controller.py`** coordena cadastro, login, refresh/logout, consulta
  do usuário atual e troca de senha.
- **`health_controller.py`** responde ao liveness e consulta se as dependências
  necessárias estão prontas.
- **`homes_controller.py`** encaminha operações de residências e membros para
  os serviços correspondentes.
- **`users_controller.py`** encaminha consulta e remoção de contas.

#### `src/modules/service/` — regras de negócio

Os serviços implementam o comportamento da aplicação, combinando validações,
decisões de negócio e operações do repositório. É o local apropriado para
regras que não devem ficar presas ao protocolo HTTP.

- **`auth_service.py`** implementa cadastro e ativação de conta pendente,
  autenticação, emissão e renovação de sessão, logout, validação do usuário
  autenticado e alteração de senha com invalidação das sessões anteriores.
- **`health_service.py`** verifica se o banco e os recursos necessários estão
  disponíveis para a API.
- **`homes_service.py`** lista e cria residências, calcula o papel do usuário
  em cada uma e coordena as operações de membros e titularidade.
- **`users_service.py`** aplica regras para listar/remover contas e adicionar
  ou remover membros de residências, incluindo as restrições de titularidade.
- **`idempotency_service.py`** impede que operações de criação sejam
  duplicadas: compara a chave e o conteúdo da requisição, reproduz respostas
  concluídas e informa conflitos ou operações ainda em andamento.

#### `src/modules/repository/` — persistência e integração

- **`supabase_repository.py`** concentra o acesso ao PostgreSQL por
  Supabase/PostgREST. Faz consultas e alterações em contas, residências,
  associações de membros, sessões e chaves de idempotência; também chama as
  funções RPC necessárias e converte registros em perfis. Controllers e
  serviços não devem montar requisições HTTP ao banco diretamente.

#### `src/modules/schemas/` — contratos e validação

Os schemas Pydantic definem os dados aceitos e devolvidos pela API. Eles validam
formatos e limites de campos e evitam que cada endpoint implemente sua própria
validação.

- **`auth_schemas.py`** define papéis, perfil de usuário e contratos de
  cadastro, login, refresh e alteração de senha.
- **`health_schemas.py`** define a resposta dos health checks.
- **`homes_schemas.py`** define entrada e resposta para residências e
  transferência de titularidade.
- **`users_schemas.py`** define a entrada para associar uma conta a uma
  residência.

#### Erros, banco, testes e documentação

- **`src/shared/errors/problem_details.py`** define o erro `Problem` e
  converte erros de negócio, validação, HTTP e falhas inesperadas para
  `application/problem+json`, conforme RFC 9457.
- **`supabase/migrations/`** guarda alterações incrementais do schema,
  funções SQL e políticas de segurança do banco. Migrações já aplicadas não
  devem ser editadas; crie uma nova para corrigir o schema.
- **`tests/test_api.py`** contém os testes automatizados de contratos,
  autenticação, autorização e respostas da API.
- **`docs/api.yml`** mantém o contrato OpenAPI; **`docs/adr/`** registra as
  decisões arquiteturais e seus motivos.
- **`.env.example`** documenta os nomes das configurações esperadas sem conter
  segredos reais; **`Dockerfile`** descreve a imagem da API; **`package.json`**
  declara dependências JavaScript auxiliares presentes no projeto.

### Fluxo de uma requisição

Em geral, uma requisição passa por esta sequência:

1. `src/app/factory.py` recebe a requisição na aplicação FastAPI e aplica os
   middlewares.
2. O módulo em `src/modules/routes/` valida os parâmetros e o corpo usando os
   schemas de `src/modules/schemas/`.
3. As dependências de `src/modules/auth/` identificam o usuário e verificam
   suas permissões antes da operação protegida.
4. O controller encaminha o caso de uso ao service correspondente.
5. O service aplica as regras de negócio e usa
   `SupabaseRepository` para consultar ou alterar os dados.
6. A resposta retorna pela rota; erros conhecidos são convertidos para o
   formato RFC 9457.

Mantenha cada responsabilidade na camada correspondente: rotas cuidam do
protocolo HTTP, controllers coordenam, services aplicam regras de negócio e o
repository concentra o acesso a dados. Não crie módulos vazios para
funcionalidades ainda não implementadas.

## 4. Contrato HTTP

Prefixo de API: `/api/v1`. O contrato executável também está disponível em
`/openapi.json` e `/docs`.

| Método | Caminho | Autenticação/permissão | Entrada | Resposta |
|---|---|---|---|---|
| GET | `/health/live` | Pública | — | `200 {"status":"ok"}` |
| GET | `/health/ready` | Pública | — | `200` quando PostgREST e tabelas de contas, residências, sessões e idempotência respondem; caso contrário `503` |
| POST | `/api/v1/auth/login` | Pública | `email`, `password` | `200` com access JWT (15 min), perfil e cookies de refresh/CSRF; `401` genérico para credenciais inválidas |
| POST | `/api/v1/auth/refresh` | Cookie de refresh + CSRF | Cookies e `X-CSRF-Token` | `200`; rotaciona refresh token; sessão expira até 30 dias após o login |
| POST | `/api/v1/auth/logout` | Cookie de refresh + CSRF, se houver sessão | Cookies e `X-CSRF-Token` | `204`; revoga sessão e remove cookies |
| POST | `/api/v1/auth/register` | Pública | `email`, `password`, `name`, `Idempotency-Key` | `201` conta criada; `409` e-mail cadastrado; replay por 24 h |
| PATCH | `/api/v1/auth/me/password` | Autenticada | `current_password`, `new_password` | `204`; invalida access e refresh sessions |
| GET | `/api/v1/auth/me` | Autenticada | — | Perfil autenticado (`id`, `email`, `name`, `role`) |
| GET | `/api/v1/users` | `master` | — | Todas as contas; acesso global reservado ao master |
| GET | `/api/v1/homes` | Bearer válido | — | Residências acessíveis e papel da conta em cada uma |
| POST | `/api/v1/homes` | Usuário autenticado | `name`, `Idempotency-Key` | `201`; cria residência e torna o criador `primary`; replay por 24 h |
| GET | `/api/v1/homes/{home_id}/users` | `primary` da casa ou `master` | UUID | Membros da residência |
| POST | `/api/v1/homes/{home_id}/users` | `primary` da casa ou `master` | `email`, `Idempotency-Key` | `201`; associa uma conta já cadastrada; replay por 24 h |
| DELETE | `/api/v1/homes/{home_id}/users/{user_id}` | `primary` da casa ou `master` | UUIDs | `204`; remove somente o vínculo, não pode remover o `primary` proprietário |
| PATCH | `/api/v1/homes/{home_id}/primary` | `master` | `user_id` | `200`; transfere a titularidade para membro existente |
| DELETE | `/api/v1/users/{user_id}` | `master` | UUID | `204`; impede autoexclusão, exclusão de master ou de primary que ainda possui casa |

O cadastro armazena hash scrypt da senha na tabela `securebase_users`; a conta
pode entrar imediatamente, sem confirmar o endereço de e-mail. Conta nova
retorna `201 Created`; e-mail já cadastrado retorna `409 Conflict`, o que pode
revelar se um endereço está registrado. O login emite um access JWT HS256
válido por 15 minutos. O frontend mantém o access token em `sessionStorage`;
o refresh token rotativo fica em cookie `HttpOnly` e expira até 30 dias após
o login. O cliente envia o token CSRF no refresh/logout; as rotas protegidas
revalidam assinatura, expiração, conta e versão da sessão.
Cadastro e login não exigem bearer; rotas protegidas exigem
`Authorization: Bearer <access_token>`. Papéis enviados pelo cliente são
rejeitados; contas criadas publicamente recebem `member`. Para adicionar alguém
a uma residência, essa pessoa precisa primeiro criar a própria conta.

### Erros

O corpo segue RFC 9457: `type`, `title`, `status`, `detail`, `instance`,
`code` e `traceId`. Validação usa `422`; ausência/token inválido usa `401`;
permissão insuficiente usa `403`; conflito de conta/operação usa `409`;
rota inexistente usa `404`; método não permitido usa `405`; dependência
indisponível usa `503`; falha inesperada usa `500`. A indisponibilidade do banco
no readiness retorna `503` com `DATABASE_UNAVAILABLE`. Todas as operações do
OpenAPI documentam uma resposta `default` com o schema Problem; onde houver
resposta `422`, ela também usa esse schema. Consulte a enumeração de
`Problem.code` em `docs/api.yml` para os códigos estáveis.
Respostas externas não incluem stack trace, chave, token ou mensagens internas
do Supabase.

### Roteiro de autenticação para desenvolvimento

1. Verifique `GET /health/ready` (`200`).
2. Registre em `POST /api/v1/auth/register` com `email`, senha (8–128
   caracteres) e `name`. Conta criada: `201`; e-mail já cadastrado: `409`.
3. Faça login em `POST /api/v1/auth/login`; guarde `access_token` em armazenamento
   de sessão protegido conforme a arquitetura do cliente. Não use a chave
   `SUPABASE_SECRET_KEY` como credencial de usuário.
4. Para rotas protegidas, envie `Authorization: Bearer <access_token>`.
5. Valide a sessão com `GET /api/v1/auth/me`. Token expirado, senha alterada ou
   conta removida exigem novo login.

Os erros usam `application/problem+json` (RFC 9457), com `code` e `traceId`;
respostas `422` incluem `fields` com os nomes dos campos inválidos.

## 5. Identidade, autorização e primeiro administrador

O backend não usa endpoints de autenticação do Supabase. A senha é armazenada
somente como hash scrypt com salt aleatório; o JWT é assinado com HMAC-SHA256 e
inclui expiração, emissor, audiência e versão de sessão. A conta e a versão são
consultadas no banco em cada requisição autenticada. Trocar a senha invalida os
tokens emitidos anteriormente. Credenciais inválidas retornam o mesmo `401`.
O sistema não confirma a titularidade do e-mail; verifique a identidade por um
canal confiável antes de promover alguém a `master`. Senhas e tokens não devem
ser registrados em logs. Configure rate limiting no gateway antes de produção.

| Perfil | Gerenciar vínculos de usuários nas residências | Usar o simulador |
|---|---:|---:|
| `master` | Todas as residências; pode transferir titularidade. Não remove o titular sem transferir antes | Sim |
| `primary` | Somente a própria residência; não remove o titular, `master` ou a si mesmo | Sim |
| `member` | Não | Sim |

Todo cadastro recebe `member`. Novas contas só podem ser criadas pelo próprio
usuário; a gestão de residências associa contas já cadastradas. Quem cria uma
residência autenticado torna-se o `primary` dela. A migration cria uma residência inicial para cada
conta que já possuía papel global `primary` e converte esse papel global para
`member`; não associa automaticamente outros usuários, pois não há como inferir
a que casa pertenciam.

Para um desenvolvedor administrador global, use `master`:

```sql
update public.securebase_users
set role = 'master', updated_at = now()
where lower(email) = lower('dev-verificado@example.com')
returning id, email, role;
```

Confirme por um canal confiável que a conta pertence ao desenvolvedor antes de
executar a consulta; o sistema não verifica a propriedade do e-mail. Confirme
que a consulta retorna exatamente uma linha. A migration adiciona
`master` ao enum `securebase_role`; ela não concede esse papel a ninguém. Não
exponha promoção de papel em rotas públicas. O `master` pode administrar todas
as residências. Antes de excluir uma conta que seja titular de alguma casa,
transfira a titularidade; não pode remover a si mesmo nem outras contas
`master`. A chave `SUPABASE_SECRET_KEY` ignora RLS, portanto só é usada no
backend, após a autorização explícita da rota.

## 6. Variáveis e ambientes

Copie `.env.example` para `.env` quando ele ainda não existir. Se já houver um
`.env` antigo, mescle nele as variáveis obrigatórias listadas abaixo sem
sobrescrever as credenciais existentes; não versione o arquivo real.

| Variável | Obrigatória | Uso |
|---|---|---|
| `ENVIRONMENT` | Não | Identifica o ambiente; padrão `development` |
| `HOST`, `PORT` | Não | Endereço local do servidor |
| `API_PREFIX` | Não | Prefixo versionado, padrão `/api/v1` |
| `CORS_ORIGINS` | Não | Lista de origens frontend permitidas |
| `SUPABASE_URL` | Sim | URL do projeto Supabase do ambiente |
| `SUPABASE_SECRET_KEY` | Sim | Chave de servidor usada exclusivamente pela API para PostgREST |
| `SUPABASE_TIMEOUT_SECONDS` | Não | Timeout das chamadas ao Supabase, máximo 30 s |
| `JWT_SECRET_KEY` | Sim | Segredo aleatório de pelo menos 32 caracteres para assinar JWTs |
| `JWT_EXPIRY_SECONDS` | Não | Validade do access token; padrão 1800 s |

No frontend, somente `VITE_API_BASE_URL` aponta para a API Python. Não são
necessárias chaves ou SDK de autenticação Supabase no frontend.

Desenvolvimento e testes devem usar um Supabase local/teste separado. Produção
deve ter projeto, chaves e segredos próprios. O CI roda testes unitários com
integrações externas simuladas; ele não acessa produção.

## 7. Configuração, migrações e execução local

PowerShell, a partir de `secure_base_back-end`:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
supabase start
supabase migration up --local
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
supabase status
```

Preencha `.env` com a URL do PostgREST e a chave de servidor local indicada por
`supabase status` e um segredo aleatório para JWT. Não copie chaves de produção.
Configure o frontend conforme
`secure_base_front-end/.env.example`. Execute:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python -m main
```

O resultado esperado é o servidor em `http://127.0.0.1:8000`, documentação em
`/docs`, `/health/live` retornando `200`, e `/health/ready` retornando `200`
depois de aplicar as migrações.

Para uma alteração de schema, crie uma nova migração SQL com o Supabase CLI,
revise SQL, RLS e impacto de compatibilidade antes de aplicar localmente. Use
sempre `--local` para desenvolvimento; não execute comandos de migração sem
confirmar explicitamente o destino.
Migrações aplicadas não devem ser editadas; correções são novas migrações.
Antes de produção, faça backup e execute a migração em staging. Esta etapa não
automatiza deploy nem rollback destrutivo.

## 8. Testes e CI

```powershell
.\.venv\Scripts\python -m ruff check src tests
.\.venv\Scripts\python -m pytest
```

Os testes cobrem health checks, hashes, JWTs e contratos de cadastro/login,
resposta RFC 9457 e permissões de membro, primary e master. O workflow `../.github/workflows/backend-ci.yml`
executa Ruff e pytest. Testes de integração com Supabase real, BOLA entre residências,
rate limiting, idempotência e e2e ainda não existem porque esses módulos/fluxos
não foram implementados.

## 9. Logs, segurança e limites conhecidos

O middleware registra método, caminho, status, duração e ID da requisição; não
registra query strings, headers de autorização, senhas ou corpos. CORS usa
origens explícitas. `securebase_users` tem RLS e não concede acesso a
`anon`/`authenticated`; somente a chave de servidor do backend acessa a tabela.
Configure rate limiting no gateway e TLS em produção.

Contas antigas do Supabase Auth não são migradas: seus hashes de senha não podem
ser reutilizados. Usuários devem se cadastrar novamente. O cadastro não confirma
a titularidade do endereço de e-mail; confirme a identidade do desenvolvedor
por outro canal antes de promover uma conta a `master`.

## 10. Próximas etapas

1. Validar Supabase CLI, migrações, cadastro, login e associação de usuários em ambiente local.
2. Implementar recuperação de senha e rate limiting antes de exposição pública.
3. Desenhar residências, membros e permissões por recurso antes de criar tabelas.
4. Implementar dispositivos, sensores, leituras, alertas e eventos somente após
   confirmar contratos funcionais do produto.
5. Adicionar auditoria, limites de requisição, observabilidade e deploy depois
   de definida a plataforma de hospedagem.

## 11. Diagnóstico de problemas

- **Configuração ausente:** verifique `.env` e nomes das variáveis. A API falha
  explicitamente quando os valores obrigatórios faltam.
- **`/health/ready` retorna 503:** confirme `supabase start`, migrações
  aplicadas, URL/chave de servidor do mesmo ambiente e acesso PostgREST.
- **`401` no login:** confira e-mail e senha.
- **`401` nas rotas protegidas:** faça login novamente; o JWT pode ter expirado
  ou ter sido invalidado por troca de senha.
- **`403` na gestão de usuários:** confira o papel persistido em
  `securebase_users`; o frontend não pode conceder esse papel.
- **Não é possível associar uma pessoa:** ela precisa criar sua própria conta
  antes de ser associada à residência.
- **CORS no browser:** inclua a origem exata em `CORS_ORIGINS` e reinicie a API.
