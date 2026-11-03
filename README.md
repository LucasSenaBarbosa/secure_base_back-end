# SecureBase Backend

API do SecureBase implementada em Python e FastAPI. O backend é responsável
pela autenticação e autorização próprias da aplicação e acessa o PostgreSQL do
Supabase por HTTPX e PostgREST. O Supabase Auth não é usado para autenticar
usuários do SecureBase.

## Arquitetura

- `src/app/` e `src/config/`: criação da aplicação e configurações.
- `src/modules/routes/`: endpoints e contratos HTTP.
- `src/modules/controller/`: coordenação das requisições.
- `src/modules/service/`: regras de negócio.
- `src/modules/repository/`: acesso a dados via Supabase/PostgREST.
- `src/modules/auth/`: autenticação e autorização.
- `src/modules/schemas/` e `src/shared/errors/`: validação e respostas de erro.
- `supabase/migrations/`: alterações versionadas do banco.
- `tests/`: testes automatizados da API.

As decisões de arquitetura estão em [`docs/adr/`](./docs/adr/). Os controles
de segurança e limites conhecidos estão em [`SECURITY.md`](./SECURITY.md).

## Requisitos

- Python 3.12 ou superior.
- Docker Desktop com WSL 2.
- Supabase CLI.

## Configuração e execução local

No PowerShell, a partir da pasta do backend:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
supabase start
supabase migration up --local
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Preencha o `.env` com os valores do **Supabase local** e um segredo JWT forte
e independente. A saída de `supabase status` contém credenciais locais: não a
compartilhe nem a salve em arquivos versionados. O procedimento completo está
em [`INSTRUCOES_BD.md`](./INSTRUCOES_BD.md).

Depois de aplicar as migrations locais, inicie a API:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m main
```

A documentação interativa fica em `http://localhost:8000/docs`. `GET /` e
`GET /health/live` são endpoints públicos; `GET /health/ready` verifica também
as dependências do banco.

## Testes e validações

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -q
supabase db lint --local --fail-on error
```

O workflow [`backend-ci.yml`](./.github/workflows/backend-ci.yml) executa Ruff,
Pytest e valida as migrations em um Supabase local. O contrato OpenAPI
executável está em `/openapi.json`; `docs/api.yml` é a cópia versionada.

## Ambientes e mudanças no banco

Desenvolvimento usa o Supabase local, independente de qualquer projeto
hospedado. Alterações estruturais são migrations SQL novas, revisadas,
versionadas e testadas localmente. Não edite migrations já aplicadas nem altere
o schema hospedado diretamente como procedimento normal.

O deploy de produção não está configurado: os provedores de hospedagem não
foram identificados e o histórico remoto de migrations precisa ser verificado
e regularizado manualmente. Os workflows atuais executam CI, não fazem deploy
e não recebem secrets de produção em branches ou pull requests. Consulte
[`INSTRUCOES.md`](./INSTRUCOES.md) para o fluxo de desenvolvimento e
[`INSTRUCOES_BD.md`](./INSTRUCOES_BD.md) para os procedimentos locais.
