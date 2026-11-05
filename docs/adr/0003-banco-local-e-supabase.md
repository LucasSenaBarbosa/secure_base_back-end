# ADR 0003 — Banco local, Supabase e PostgreSQL

- **Status:** Aceita.
- **Data:** 2026-11-01.

## Contexto

O SecureBase é composto por um frontend React/Vite e uma API Python/FastAPI.
O backend implementa autenticação própria: armazena hashes de senha em
`public.securebase_users`, emite JWTs SecureBase e não usa Supabase Auth para
login. O acesso às tabelas e funções do PostgreSQL é feito pelo repositório
`src/modules/repository/supabase_repository.py`, que chama a API REST
PostgREST.

O schema é mantido em arquivos SQL na pasta `supabase/migrations/`, e a
configuração local do Supabase está em `supabase/config.toml`. É necessário
evitar que o desenvolvimento altere dados ou estrutura do banco de produção
sem revisão e autorização explícitas. Também é necessário que CI possa validar
as migrations sem credenciais de produção.

## Decisões

1. **Separar os bancos de desenvolvimento e produção.**
   - Desenvolvimento usa uma instância Supabase local, iniciada pelo Supabase
     CLI sobre Docker Desktop.
   - Produção usa um projeto Supabase hospedado independente, com URL, chaves
     e segredos próprios.
   - Alterações no banco local não se propagam automaticamente para produção.
     Dados, credenciais e estado dos dois ambientes não são compartilhados.

2. **Usar Supabase como plataforma do banco.**
   - O Supabase fornece PostgreSQL e a API PostgREST usada pelo gateway HTTP
     atual do backend.
   - Supabase Auth não é a autenticação de usuários do SecureBase. A API
     continua responsável por senha, sessões, access JWTs e autorização.
   - O Supabase CLI gerencia o ambiente local e o histórico de migrations.

3. **Usar PostgreSQL como banco relacional.**
   - Contas, residências, associações, sessões de refresh, idempotência,
     constraints e funções transacionais ficam no PostgreSQL.
   - Mudanças estruturais são migrations SQL novas, revisadas e versionadas em
     `supabase/migrations/`.
   - Migrations devem ser aplicadas e testadas localmente antes de qualquer
     proposta de aplicação em produção. Migrations já aplicadas não devem ser
     alteradas; correções são migrations adicionais.

4. **Manter a aplicação de migrations remotas explícita e protegida.**
   - O workflow `backend-ci.yml` define uma etapa `deploy-migrations` que roda
     somente em pushes para `main`, depois de CI e validação local das
     migrations. Ela usa o GitHub Environment `production`, verifica o
     histórico remoto, bloqueia operações selecionadas, faz dry-run e então
     aplica migrations pendentes.
   - O workflow aplica migrations do banco; não publica a aplicação.
   - O arquivo do workflow não configura as proteções do GitHub Environment.
     Revisores obrigatórios, secrets, variáveis e identificação inequívoca do
     projeto de destino devem ser verificados na configuração do repositório
     antes de permitir uma execução em produção.
   - O estado atual do projeto remoto não é comprovado por esta decisão. Uma
     divergência no histórico deve bloquear o processo e ser regularizada por
     procedimento manual revisado, sem reparação automática.

## Alternativas consideradas

- **Usar o projeto Supabase de produção durante o desenvolvimento:** rejeitado,
  pois mistura dados e aumenta o risco de alterações acidentais no ambiente
  real.
- **Executar PostgreSQL instalado diretamente em cada máquina:** rejeitado
  para o fluxo padrão, pois divergiria da configuração e dos serviços locais
  que o projeto já define pelo Supabase CLI.
- **Usar outro banco relacional:** não escolhido, pois o backend e as
  migrations existentes já usam PostgreSQL e recursos do Supabase.
- **Executar migrations remotas sem controles no CI:** rejeitado. A etapa
  remota deve depender de verificações aprovadas, destino explícito e
  configuração protegida do GitHub Environment; nenhuma reparação automática
  do histórico remoto é permitida.

## Consequências

- Desenvolvedores precisam de Docker Desktop, WSL 2 e Supabase CLI.
- O fluxo local padrão é iniciar Supabase, aplicar migrations com destino
  explicitamente local, conferir o estado e rodar testes.
- Cada ambiente requer suas próprias variáveis. A chave de serviço Supabase e
  `JWT_SECRET_KEY` são segredos de servidor; nunca podem ser versionados nem
  enviados ao frontend.
- A chave de serviço Supabase ignora RLS. A API deve continuar aplicando
  autenticação e autorização SecureBase antes das operações administrativas.
- CI de branches e pull requests valida o backend e migrations em Supabase
  local sem acessar o banco de produção. Em pushes para `main`, o job de
  migrations também pode acessar o projeto configurado no Environment
  `production`, após as verificações definidas no workflow.
- A configuração do Environment e o histórico remoto precisam ser verificados
  separadamente; a existência do job não prova que o deploy esteja configurado
  nem que migrations tenham sido aplicadas.

## Segurança

- `.env`, arquivos temporários do Supabase e segredos de produção não devem ser
  versionados. `.env.example` contém somente placeholders.
- Chaves locais são geradas pelo Supabase CLI e não são credenciais de
  produção. Chaves do Supabase de produção são obtidas no painel do projeto e
  configuradas somente no ambiente de execução protegido.
- `JWT_SECRET_KEY` pertence à autenticação própria SecureBase; não é uma chave
  Supabase e deve ser independente em cada ambiente.
- A chave Supabase usada pelo backend é enviada somente em chamadas de servidor
  ao PostgREST. A chave nunca deve ser colocada em variáveis `VITE_*` ou no
  bundle do frontend.
- Branches e pull requests não recebem secrets de produção. O job de migrations
  em `main` usa secrets e variáveis associados ao Environment `production`;
  revisores obrigatórios e outras restrições precisam ser configurados no
  próprio GitHub Environment.
- Não executar manualmente `supabase link`, `supabase db push`,
  `supabase db reset` ou `supabase migration repair` para tentar corrigir o
  histórico remoto. A etapa automatizada não autoriza corrigir ou reparar
  divergências sem revisão.
