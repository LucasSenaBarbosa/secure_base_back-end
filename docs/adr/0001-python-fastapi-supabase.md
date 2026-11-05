# ADR 0001 — FastAPI, PostgreSQL e autenticação própria

- **Status:** Aceita.
- **Data:** 2026-10-25.

## Contexto

O frontend é uma aplicação React/Vite e o backend é Python/FastAPI. A decisão
inicial de usar Supabase Auth foi substituída. O PostgreSQL do Supabase continua
como banco de contas; cadastro, senha e emissão/validação de JWT passam a ser
responsabilidade da API SecureBase. O cadastro não confirma a titularidade do
endereço de e-mail.

## Decisão

- Usar FastAPI para expor a API Python versionada em `/api/v1`.
- Usar tabela própria `public.securebase_users` acessada pelo backend por
  PostgREST e protegida por RLS.
- Armazenar senhas com scrypt; emitir JWT HS256 com chave privada do backend.
- Não confirmar e-mails; novas contas definem a própria senha durante o cadastro.
- Manter papéis em `public.securebase_users`; o cliente não recebe permissão para
  ler ou editar essa tabela diretamente.
- Usar a chave de servidor Supabase somente no backend para acesso ao banco.
- Usar Supabase CLI localmente para manter PostgreSQL compatível com a
  instância de produção.
- Conceder o primeiro papel global `master` manualmente após criar a conta do
  administrador. O papel `primary` é associado a uma residência: quem cria a
  residência autenticado torna-se seu titular.
- Emitir access JWT HS256 válido por 15 minutos e refresh token opaco, rotativo,
  em cookie `HttpOnly`; a sessão tem expiração absoluta de 30 dias.
- Persistir somente o hash do refresh token. Associar refresh sessions a uma
  família e à versão de autenticação da conta para revogação no logout e após
  alteração de senha.
- Exigir `Idempotency-Key` no cadastro, criação de residência e associação de
  membro. Reproduzir respostas concluídas por 24 horas e rejeitar a reutilização
  da chave com payload diferente.
- Usar `PATCH` para alterações parciais de senha e titularidade.
- Padronizar falhas HTTP como `application/problem+json` (RFC 9457), com código
  estável e `traceId`; códigos são documentados no contrato OpenAPI.

## Alternativas consideradas

- Supabase Auth: substituído para que SecureBase controle autenticação própria.
- Login por nome de usuário: não adotado; o identificador permanece o e-mail.
- Papéis em metadados editáveis pelo usuário: rejeitados por permitirem
  escalada de privilégio.

## Consequências e segurança

- As contas antigas salvas no navegador não são migradas: não há uma fonte
  confiável no servidor para verificar suas senhas ou papéis.
- A API armazena hash de senha, emite access JWT com expiração configurável e
  valida o estado atual da conta em cada requisição autenticada.
- A proteção contra abuso exige rate limiting configurado no gateway.
- E-mails não são enviados pela API; residências só podem associar contas já
  cadastradas.
- Sem confirmação de e-mail, a identidade dos administradores deve ser
  verificada por um canal confiável antes da promoção.
- Contas anteriores do Supabase Auth não podem ter seus hashes de senha
  reutilizados e precisam se cadastrar novamente.
- O primeiro administrador precisa ser promovido manualmente no banco.
- Chamadas do backend usam uma chave de servidor que ignora RLS. Por isso,
  as dependências de autorização verificam o perfil exigido pela operação:
  `master` para ações globais ou `primary` para ações na própria residência,
  antes da operação administrativa protegida. A chave nunca é enviada ao
  frontend.
- Refresh tokens roubados não podem ser reutilizados após a rotação; a família
  é revogada se a versão de autenticação divergir. A expiração não é estendida
  a cada rotação.
- Operações idempotentes reduzem duplicações causadas por retries do cliente,
  mas reserva, mutação e persistência da resposta não são uma única transação
  PostgreSQL; uma falha entre essas etapas pode exigir aguardar a expiração da
  chave para tentar novamente.
