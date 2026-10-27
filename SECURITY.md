# Segurança

## Segredos

- Nunca coloque o `.env` do backend nem chaves Supabase no controle de versão.
- `SUPABASE_SECRET_KEY` e `JWT_SECRET_KEY` existem somente no servidor.
- Senhas e tokens não são registrados nos logs.

## Controles implementados

- A API valida JWTs HS256 próprios, com assinatura, emissor, audiência,
  expiração e versão de sessão.
- Senhas são armazenadas com scrypt, salt aleatório e comparação em tempo
  constante.
- A autorização por ação fica em `src/modules/auth/middleware.py` e consulta o
  papel persistido no banco após validar o JWT.
- `master` é um papel global e pode administrar todas as residências e contas.
  `primary` é um papel da residência e só administra os vínculos de membros
  das casas que possui. Nenhum perfil pode remover a própria conta; contas
  `master` não podem ser removidas pela API.
- Os vínculos de residência ficam em `securebase_home_members`; remover um
  membro de uma casa não apaga sua conta nem os vínculos com outras casas.
- Perfis não podem ser lidos nem alterados diretamente pelo cliente; RLS está
  habilitado e os privilégios `anon`/`authenticated` foram revogados.
- Cadastros públicos recebem `member`; papéis enviados pelo cliente são
  rejeitados. Para associar alguém a uma casa, a conta precisa estar cadastrada.
- A migration de residências converte os papéis globais `primary` legados em
  `member` após criar as respectivas casas; a titularidade passa a ser mantida
  em `securebase_homes.primary_user_id`.
- O cadastro não confirma a titularidade do e-mail. As contas podem ser
  criadas imediatamente, e a resposta é neutra para não revelar se a conta já
  existe; use um canal confiável para verificar a identidade antes de conceder
  privilégios `master`.
- O papel `master` só pode ser atribuído manualmente no banco; não há endpoint
  de autopromoção.
- Erros HTTP usam `application/problem+json` sem detalhes internos do provedor.
- CORS é limitado às origens configuradas e o corpo de criação de usuário não
  aceita papel.

## Revisões operacionais pendentes

Antes da produção, configure SMTP autenticado com TLS, rate limiting no gateway,
segredos fortes/rotacionáveis e HTTPS; teste autorização usando contas separadas.
Não promova um administrador sem verificar por um canal confiável a identidade
do usuário e o identificador da conta.
