# SecureBase Backend

API do SecureBase implementada em Python e FastAPI. O backend é responsável
pela autenticação e autorização próprias da aplicação e acessa o PostgreSQL do
Supabase por HTTPX e PostgREST. O Supabase Auth não é usado para autenticar
usuários do SecureBase.

## Arquitetura

- O backend é organizado por camadas (*layer-first*), com uma responsabilidade
  técnica por camada e o nome da funcionalidade nos arquivos. Essa separação
  aplica o Princípio da Responsabilidade Única; consulte as
  [ADRs 0005](./docs/adr/0005-organizacao-layer-first.md) e
  [0006](./docs/adr/0006-principio-responsabilidade-unica.md).
- `src/app/` e `src/config/`: criação da aplicação e configurações.
- `src/modules/routes/`: endpoints e contratos HTTP.
- `src/modules/controller/`: coordenação das requisições.
- `src/modules/service/`: regras de negócio.
- `src/modules/repository/`: acesso a dados via Supabase/PostgREST.
- `src/modules/auth/`: autenticação e autorização.
- `src/modules/schemas/` e `src/shared/errors/`: validação e respostas de erro.
- `supabase/migrations/`: alterações versionadas do banco.
- `tests/`: testes automatizados da API.

O laboratório de otimização de sensores (NSGA-II com pymoo) está descrito em
[`docs/optimization.md`](./docs/optimization.md), com o modelo matemático,
os endpoints, como testar e as limitações.

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

A documentação interativa fica em `http://localhost:8000/docs`; o topo da
página traz o passo a passo para obter um JWT e usá-lo no botão **Authorize**
(texto em [`src/app/openapi_docs.py`](./src/app/openapi_docs.py)). `GET /` e
`GET /health/live` são endpoints públicos; `GET /health/ready` verifica também
as dependências do banco.

## Testes e validações

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -q
supabase db lint --local --fail-on error
```

O workflow [`backend-ci.yml`](./.github/workflows/backend-ci.yml) executa Ruff,
Pytest e valida as migrations em um Supabase local. Em um `push` para `main`,
ele também define uma etapa de aplicação de migrations no Supabase associado
ao GitHub Environment `production`, após as verificações e os controles de
segurança do workflow. Isso não publica a aplicação; a configuração do
Environment, das proteções e das credenciais precisa ser verificada no GitHub.
O contrato OpenAPI executável está em `/openapi.json`; `docs/api.yml` é a cópia
versionada.

## Ambientes e mudanças no banco

Desenvolvimento usa o Supabase local, independente de qualquer projeto
hospedado. Alterações estruturais são migrations SQL novas, revisadas,
versionadas e testadas localmente. Não edite migrations já aplicadas nem altere
o schema hospedado diretamente como procedimento normal.

O deploy da aplicação não está configurado. O workflow de migrations de
produção está definido, mas a configuração e o histórico do projeto remoto não
foram validados por esta documentação; sua existência não comprova que uma
migration já tenha sido aplicada. Branches e pull requests executam CI sem
receber secrets de produção; a etapa de migrations só roda em `main` e usa o
GitHub Environment `production`. Consulte
[`INSTRUCOES.md`](./INSTRUCOES.md) para o fluxo de desenvolvimento e
[`INSTRUCOES_BD.md`](./INSTRUCOES_BD.md) para os procedimentos locais.
