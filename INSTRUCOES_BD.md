# Manual do banco de dados do SecureBase

Este manual descreve a arquitetura de persistência do SecureBase e o fluxo
local para iniciar o Supabase, configurar o backend, entender o schema e
validar migrations. O desenvolvimento atual usa exclusivamente o Supabase
local, executado pela Supabase CLI sobre Docker. As migrations ainda não foram
aplicadas ao banco remoto; nenhum estado remoto é considerado validado por
este documento.

## 1. Arquitetura e responsabilidades

O banco é PostgreSQL, administrado pela plataforma Supabase. O backend não
abre uma conexão PostgreSQL diretamente: `src/modules/repository/
supabase_repository.py` usa HTTPX para chamar a API REST/PostgREST do Supabase
e as funções RPC definidas no schema `public`.

O fluxo normal de dados é:

1. A rota e o backend validam a requisição, a identidade e a autorização
   SecureBase.
2. Controllers e services encaminham o caso de uso ao `SupabaseRepository`.
3. O repository envia uma requisição HTTP ao PostgREST usando a URL, o timeout
   e a chave privilegiada configurados no ambiente do backend.
4. Operações que precisam ser atômicas chamam funções PostgreSQL publicadas
   como RPC.
5. O resultado é validado pelo backend e convertido em schemas da API.

O Supabase Auth está habilitado na configuração local como serviço da
plataforma, mas **não autentica usuários SecureBase**. A aplicação possui seu
próprio cadastro, hashes de senha, JWTs, refresh sessions, cookies e
autorização. A tabela `user_profiles` e o trigger ligados a `auth.users`
pertencem ao legado de integração com Supabase Auth; a autenticação atual usa
`securebase_users`.

O frontend conversa apenas com a API HTTP. Não recebe `SUPABASE_SECRET_KEY`,
não acessa PostgREST diretamente e não usa Supabase Auth para login.

## 2. Isolamento entre ambientes

O ambiente local e qualquer projeto Supabase hospedado são bancos distintos:
não compartilham schema, dados, URLs ou credenciais. A URL e a chave local
devem ser copiadas da execução local da CLI para o `.env` do backend. O
`JWT_SECRET_KEY` é outro segredo, próprio da autenticação SecureBase.

O backend deve usar Supabase local durante desenvolvimento. Não copie para o
`.env` local chaves, URLs ou segredos de ambientes hospedados. Não publique a
saída de `supabase status`: ela pode conter credenciais geradas localmente.
Também não versione `.env` nem arquivos temporários do CLI.

**Estado nesta revisão:** migrations e validações foram executadas no ambiente
local. Nenhuma migration foi aplicada a um banco remoto. O estado e o histórico
remotos não estão confirmados neste manual.

## 3. Pré-requisitos para Windows

O fluxo documentado foi preparado para Windows com:

- Windows 10 ou 11 e virtualização habilitada no firmware.
- WSL 2 atualizado.
- Docker Desktop em execução.
- Supabase CLI disponível no PowerShell.
- Python 3.12 ou superior para a API e os testes.
- Git para acompanhar migrations e alterações do projeto.

O Docker Desktop executa os serviços locais em containers. Se o Docker não
iniciar, confira o status do WSL, a virtualização e o estado do Docker Desktop
antes de iniciar o Supabase:

```powershell
wsl --status
wsl --version

docker --version
docker info
```

Consulte as páginas oficiais para instalação e requisitos:

- [Instalar WSL](https://learn.microsoft.com/windows/wsl/install)
- [Docker Desktop para Windows](https://docs.docker.com/desktop/setup/install/windows-install/)
- [Instalação local do Supabase](https://supabase.com/docs/guides/local-development/cli/getting-started)

Uma forma usada neste ambiente Windows para instalar a CLI é o Scoop:

```powershell
scoop bucket add supabase https://github.com/supabase/scoop-bucket.git
scoop install supabase
supabase --version
```

A CLI verificada durante esta revisão era `2.122.0`. O workflow de CI usa a
ação `supabase/setup-cli` com `v2.stable`; os desenvolvedores devem conferir a
versão realmente instalada em seu terminal com `supabase --version`.

## 4. Configuração Supabase do projeto

A configuração local está em [`supabase/config.toml`](./supabase/config.toml).
Ela identifica o projeto `securebase-backend`, configura os schemas da API e
define as portas locais. Os serviços e portas explicitamente definidos no
arquivo são:

| Serviço | Porta local | Observação |
|---|---:|---|
| API Supabase / PostgREST | `54321` | O backend usa esta URL base e o endpoint `/rest/v1` |
| PostgreSQL | `54322` | Banco local; não é a URL REST usada pelo repository |
| Shadow database | `54320` | Usado por tarefas locais da CLI |
| Supabase Studio | `54323` | Interface web para inspecionar o banco local |
| Inbucket | `54324` | Interface local do serviço de e-mail |
| SMTP do Inbucket | `54325` | Porta SMTP local |
| POP3 do Inbucket | `54326` | Porta POP3 local |

O arquivo também habilita API, Studio, Inbucket e Auth e configura URLs de
redirecionamento locais. A autenticação do Supabase Auth e o Inbucket não
substituem a autenticação própria SecureBase nem significam que envio de
mensagens pela aplicação esteja implementado.

## 5. Inicializar e encerrar o ambiente

Abra o PowerShell na raiz de `secure_base_back-end`. Confira primeiro o
diretório, pois a CLI usa a pasta `supabase/` do projeto corrente:

```powershell
Get-Location
Test-Path .\supabase\config.toml
```

Inicie os serviços locais:

```powershell
supabase start
```

Consulte os endereços e chaves gerados para uso **local**:

```powershell
supabase status
```

A saída contém valores sensíveis mesmo quando destinados apenas ao computador
local. Use-a somente para preencher o `.env` e não a copie para mensagens,
logs públicos, documentação ou issues. O `.env.example` contém placeholders e
pode ser copiado apenas quando o arquivo `.env` ainda não existir: 

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}
```

Se `.env` já existir, edite-o com cuidado e mescle as variáveis que faltarem;
não sobrescreva valores locais existentes. Consulte a seção seguinte para os
nomes, padrões e restrições.

Para inspecionar o Supabase local, abra `http://127.0.0.1:54323` depois que
`supabase start` informar que os serviços estão prontos. Confirme que é o
Studio local antes de executar SQL. Para encerrar os containers locais ao
terminar o trabalho:

```powershell
supabase stop
```

Esse comando serve para parar o ambiente local; não use comandos de reset ou
de remoção de volumes como rotina.

## 6. Variáveis do backend

O backend lê `.env` na raiz do repositório, por meio de
`src/config/settings.py`. Se a variável também existir no ambiente do processo,
as configurações do ambiente são carregadas pelo Pydantic Settings. Os valores
do `.env.example` são apenas exemplos e placeholders.

| Variável | Obrigatória | Padrão / validação | Uso |
|---|---|---|---|
| `ENVIRONMENT` | Não | `development` | Identifica o ambiente. `production`, `prod` e `staging` exigem HTTPS para Supabase e origens CORS |
| `HOST` | Não | `127.0.0.1` | Endereço de escuta do backend |
| `PORT` | Não | `8000`; inteiro entre `1` e `65535` | Porta HTTP do backend |
| `API_PREFIX` | Não | `/api/v1` | Prefixo das rotas versionadas; começa com `/` e não termina com `/` |
| `CORS_ORIGINS` | Não | `http://localhost:5173` | Origens HTTP(S) separadas por vírgula; não aceita caminhos, credenciais, query ou fragmento |
| `SUPABASE_URL` | Sim | URL válida | URL do serviço REST do mesmo Supabase local |
| `SUPABASE_SECRET_KEY` | Sim | Chave local não vazia | Chave privilegiada usada somente no backend para PostgREST |
| `SUPABASE_TIMEOUT_SECONDS` | Não | `5`; maior que `0` e até `30` | Timeout das chamadas HTTP ao Supabase |
| `JWT_SECRET_KEY` | Sim | Pelo menos 32 caracteres | Segredo da autenticação própria SecureBase, independente da chave Supabase |
| `JWT_EXPIRY_SECONDS` | Não | `900`; entre `300` e `86400` | Duração do access token em segundos |
| `REFRESH_TOKEN_EXPIRY_SECONDS` | Não | `2592000`; entre `86400` e `2592000` | Duração máxima da sessão de refresh em segundos |

No estado local padrão, a URL REST tem a forma `http://127.0.0.1:54321`;
confirme o valor efetivo na saída local da CLI em vez de copiar uma URL de
outro ambiente. O endereço do banco PostgreSQL na porta `54322` não deve ser
usado como `SUPABASE_URL`, pois o repository chama PostgREST.

Não reutilize a chave Supabase como `JWT_SECRET_KEY`. Não coloque nenhuma
dessas chaves em `VITE_*`, no frontend, em exemplos versionados ou em logs.

## 7. Estrutura atual do banco

As migrations atuais estão em `supabase/migrations/`, em ordem cronológica.
Elas definem o schema `public` usado pelo backend:

### 7.1. Perfis legados e papéis

`20261025000100_user_profiles.sql` cria o enum `public.securebase_role` com
`primary` e `member`, a tabela legada `public.user_profiles` referenciando
`auth.users`, a função `sync_securebase_user_profile()` e o trigger
`on_auth_user_created_or_updated`. Esse objeto reflete a integração anterior
com usuários do Supabase Auth; o login atual da aplicação não usa essa tabela.

`20261025000300_master_admin_role.sql` adiciona `master` ao enum. A aplicação
usa `master` para autorização global; a titularidade `primary` é associada a
uma residência, com `primary_user_id`, e não deve ser confundida com um
administrador global.

### 7.2. Contas SecureBase

`public.securebase_users`, criada em
`20261025000200_securebase_accounts.sql`, é a tabela de contas da autenticação
própria. Seus campos incluem identificador UUID, e-mail, nome, hash de senha,
papel, estado de verificação/convite, versão de autenticação e timestamps.

O índice `securebase_users_email_lower_idx` impede duplicidade ignorando a
capitalização do e-mail. Há índices únicos parciais para hashes de tokens de
verificação e convite e constraints de tamanho para e-mail e nome. A constraint
`securebase_users_auth_state` representa os estados com senha ou com convite
pendente. O fluxo público atual cria a conta com hash de senha; não há envio
automático de convite ou recuperação de senha.

### 7.3. Residências e membros

`20261025000400_households.sql` cria:

- `public.securebase_homes`: residências com identificador, nome, titular
  (`primary_user_id`) referenciado a `securebase_users` e timestamps. O nome
  tem constraint de tamanho.
- `public.securebase_home_members`: associação entre residência e conta. A
  chave primária composta `(home_id, user_id)` impede vínculos duplicados; as
  referências usam `ON DELETE CASCADE`.

Índices apoiam consultas pelo titular e pelo usuário associado. A migration
cria uma residência inicial para contas que tinham o papel global `primary` e
depois as altera para `member`; ela não infere os demais membros de cada casa.
Hoje, um usuário pode participar de várias residências.

### 7.4. Sessões e idempotência

`20261025000500_auth_sessions_and_idempotency.sql` cria:

- `public.securebase_refresh_sessions`: hash do refresh token, usuário, família
  da sessão, versão de autenticação, expiração, revogação, hash substituto e
  data de criação. Índices atendem consultas por usuário, família e expiração.
- `public.securebase_idempotency_keys`: escopo e hash da chave, fingerprint da
  requisição, resposta/status concluídos e prazos. A chave primária é
  `(scope, key_hash)` e respostas são mantidas por 24 horas.

As funções RPC dessa migration concentram operações transacionais:

| Função | Finalidade |
|---|---|
| `securebase_create_refresh_session` | Criar sessão e remover um lote limitado de sessões expiradas |
| `securebase_rotate_refresh_session` | Validar e rotacionar refresh token, detectar reutilização, versão desatualizada e expiração |
| `securebase_revoke_refresh_session` | Revogar a família associada a um token |
| `securebase_revoke_user_refresh_sessions` | Revogar sessões de uma conta |
| `securebase_claim_idempotency_key` | Reservar chave, identificar replay, conflito ou operação em andamento |
| `securebase_complete_idempotency_key` | Registrar status e corpo de uma resposta concluída |
| `securebase_release_idempotency_key` | Liberar reserva após falha do caso de uso |

`20261101000100_qualify_refresh_session_family_id.sql` substitui a função de
rotação qualificando `family_id` com o alias da tabela nos caminhos que revogam
a família quando o token foi reutilizado ou sua versão ficou desatualizada.
A migration original foi preservada. A correção foi aplicada e validada no
Supabase local; isso não afirma que tenha sido aplicada remotamente.

## 8. RLS, privilégios e limites do acesso

As migrations habilitam Row Level Security em `user_profiles`,
`securebase_users`, `securebase_homes`, `securebase_home_members`,
`securebase_refresh_sessions` e `securebase_idempotency_keys`. Também revogam
privilégios diretos de `anon` e `authenticated`; as tabelas próprias da
aplicação concedem operações ao papel de serviço usado pelo backend. As
funções RPC restringem execução e concedem os privilégios necessários ao
serviço.

O repository usa uma chave privilegiada do servidor, que pode ignorar RLS.
Portanto, autorização não é delegada ao banco nem ao navegador: as rotas e
dependências SecureBase verificam a identidade e o papel antes de operações
administrativas. A chave nunca deve aparecer no frontend.

Não há políticas RLS por usuário que permitam acesso direto do cliente às
tabelas SecureBase. Não crie permissões ou políticas adicionais sem revisar
todo o caminho de autorização e adicionar migrations e testes apropriados.

## 9. Histórico e validação de migrations

O histórico versionado e a ordem atual são:

1. `20261025000100_user_profiles.sql`
2. `20261025000200_securebase_accounts.sql`
3. `20261025000300_master_admin_role.sql`
4. `20261025000400_households.sql`
5. `20261025000500_auth_sessions_and_idempotency.sql`
6. `20261101000100_qualify_refresh_session_family_id.sql`

As migrations são a fonte versionada da estrutura do banco. Revise cada
alteração SQL, impacto de compatibilidade, grants, RLS, índices, funções e
triggers. Versione uma migration nova no mesmo pull request da alteração que
depende dela. Não modifique nem remova uma migration que possa ter sido aplicada
em algum ambiente; corrija por meio de nova migration cronologicamente
posterior.

Durante esta revisão, a sequência foi consultada no Supabase local e
`supabase db lint --local --fail-on error` não apontou erros. A validação
local não comprova o estado remoto nem substitui testes funcionais.

## 10. Criar e testar uma migration localmente

Execute os comandos abaixo somente no PowerShell aberto na raiz do backend,
com Supabase local iniciado:

```powershell
supabase migration new descricao_da_alteracao
```

Edite o novo arquivo SQL criado em `supabase/migrations/`. Antes de aplicá-lo,
revise a migration original relacionada, a ordem, constraints, efeitos sobre
dados já existentes, privilégios e compatibilidade da API.

Aplique migrations pendentes **somente ao banco local**:

```powershell
supabase migration up --local
```

Confira a lista local e faça lint do schema:

```powershell
supabase migration list --local
supabase db lint --local --fail-on error
```

O lint verifica erros de schema na instância escolhida; não executa todos os
casos de uso nem comprova que uma função funciona para todas as sequências de
sessão. Depois da migration, execute também os testes do backend e teste os
fluxos afetados com dados sintéticos e descartáveis no Supabase local.

Para as migrations atuais, o CI de backend inicia um projeto Supabase
temporário, suprime a saída da inicialização para não registrar credenciais
locais, executa `supabase migration up --local` e depois executa
`supabase db lint --local --fail-on error`. Os testes de Pytest usam um
repository em memória; não são integração do pytest com o PostgREST local. Não
há suíte SQL funcional versionada que substitua a revisão dos fluxos de banco.

## 11. Testes locais da API que acessam o banco

O backend usa estas relações para readiness:

- `securebase_users`
- `securebase_homes`
- `securebase_home_members`
- `securebase_refresh_sessions`
- `securebase_idempotency_keys`

Inicie o Supabase local, confirme que as migrations locais foram aplicadas e
preencha o `.env` com URL e chave do mesmo ambiente. Inicie a API conforme
[`README.md`](./README.md) e verifique:

- `GET /health/live`: confirma que o processo da API está respondendo.
- `GET /health/ready`: confirma também acesso PostgREST e recursos de banco
  necessários; retorna `503` com `DATABASE_UNAVAILABLE` se a dependência/schema
  não estiver pronto.
- Cadastro, login, refresh, logout e operações de residências devem usar
  contas sintéticas e somente o Supabase local.

Na raiz do backend, execute a suíte automatizada e o lint:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -q
supabase db lint --local --fail-on error
```

Pytest usa um gateway falso para verificar os contratos e as regras da API.
Para verificar conectividade manual ao REST, use apenas um GET sem alteração
de dados e sem incluir valores de segredos no comando ou no relatório. Não
execute INSERT, UPDATE ou DELETE para conferir conectividade.

## 12. Segurança e bloqueio de operações remotas

Para este fluxo de desenvolvimento, não execute:

```text
supabase link
supabase db push
supabase db reset
supabase migration repair
```

Não use `supabase migration up` sem `--local` e sem conferir a raiz do projeto.
Não passe `--linked`, `--project-ref` ou uma URL remota para comandos de lint
ou migration. Não conecte ferramentas de banco ao endereço de produção para
testes.

O histórico remoto de migrations não foi regularizado automaticamente e a
configuração de produção permanece pendente. Se uma divergência remota impedir
um deploy futuro, interrompa o processo e peça regularização manual revisada.
Não tente alinhar o histórico com `repair`, aplicar migrations ou alterar o
schema remoto por conta própria.

Produção deve ter projeto, URL, chave Supabase e segredo JWT independentes.
Secrets de produção só poderão ser configurados após decisão de hospedagem e
aprovação do processo, restritos ao GitHub Environment `production`, com
revisores obrigatórios. Branches e pull requests não devem ter acesso a eles.

Consulte também [ADR 0003 — Banco local, Supabase e PostgreSQL](./docs/adr/0003-banco-local-e-supabase.md)
para o racional arquitetural e [README.md](./README.md) para a visão geral do
projeto.

## 13. Diagnóstico de problemas

### Docker ou Supabase não inicia

- Confirme `docker info` e se o Docker Desktop está em execução.
- Confira WSL 2, virtualização e recursos disponíveis.
- Verifique se as portas listadas na seção 4 já estão em uso.
- Execute `supabase status` para consultar o estado dos serviços; proteja a
  saída porque ela contém credenciais locais.

### A API não consegue acessar PostgREST

- Confirme que `SUPABASE_URL` aponta para a URL REST local, normalmente na
  porta `54321`, e não para a porta PostgreSQL `54322`.
- Confirme que URL e `SUPABASE_SECRET_KEY` foram obtidas do mesmo `supabase
  status` local.
- Confira se o container do banco e o serviço REST estão prontos.
- `401` ou `403` normalmente indica chave ou permissão incompatível; `404`
  pode indicar URL, recurso ou schema ausente; falhas de conexão podem indicar
  serviço parado, porta ocupada ou URL incorreta.
- Não resolva erros usando credenciais de produção.

### Readiness retorna `503`

`GET /health/live` verifica somente o processo. `GET /health/ready` também
verifica PostgREST e os recursos necessários. Confirme que a CLI está ativa,
que as migrations foram aplicadas localmente e que as variáveis apontam para
esse mesmo projeto.

### Lint de banco falha

Leia o nome da função, tabela ou coluna indicada e confirme que o comando foi
executado com `--local`. Não edite uma migration antiga se ela já foi aplicada.
Prepare uma migration corretiva nova, aplique-a apenas localmente e repita o
lint e os testes pertinentes. Se a divergência envolver histórico remoto,
pare e solicite regularização manual; não tente repará-la automaticamente.
