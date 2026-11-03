# Desenvolvimento do backend

Este documento complementa o [README](./README.md) com as regras de manutenção
do código. Configuração e procedimentos do banco estão em
[INSTRUCOES_BD.md](./INSTRUCOES_BD.md); decisões arquiteturais estão em
[docs/adr/](./docs/adr/) e controles de segurança em [SECURITY.md](./SECURITY.md).

## Responsabilidades do código

- Rotas validam o protocolo HTTP e chamam controllers; não devem acessar o
  banco nem concentrar regras de negócio.
- Controllers coordenam os casos de uso; services implementam regras da
  aplicação.
- `SupabaseRepository` concentra as chamadas HTTPX ao PostgREST.
- Autenticação e autorização pertencem ao backend. A aplicação usa JWTs
  SecureBase e não usa Supabase Auth para login.
- Schemas definem os contratos de entrada e saída. Erros HTTP seguem o formato
  RFC 9457 implementado em `src/shared/errors/`.

Mantenha esse fluxo e os módulos existentes. Não crie camadas ou módulos vazios
para funcionalidades ainda não implementadas.

## Alterações e validação

Antes de abrir um pull request, execute na raiz do backend:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -q
supabase db lint --local --fail-on error
```

Alterações de schema devem seguir o fluxo local de
[INSTRUCOES_BD.md](./INSTRUCOES_BD.md). Não altere migrations já aplicadas;
adicione uma migration corretiva versionada. Nunca use credenciais reais em
testes ou logs.

## Segredos, CI e deploy

- Não versione `.env`, chaves, tokens ou dados locais do Supabase. Use
  `.env.example` apenas como modelo.
- `SUPABASE_SECRET_KEY` e `JWT_SECRET_KEY` são segredos de servidor. Não os
  coloque no frontend nem em variáveis `VITE_*`.
- Pushes e pull requests executam CI independente no backend e no frontend.
  Configure os checks como obrigatórios nas regras de proteção da branch `main`.
- CI não acessa secrets de produção. Deploy e aplicação de migrations remotas
  permanecem desabilitados até que hospedagem e histórico do banco sejam
  verificados e aprovados.
