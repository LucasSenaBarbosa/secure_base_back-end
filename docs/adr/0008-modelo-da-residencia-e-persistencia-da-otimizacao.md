# ADR 0008 — Modelo da residência e persistência da otimização

- **Status:** Aceita.
- **Data:** 2026-11-06.

## Contexto

Antes desta decisão, uma residência (`securebase_homes`) tinha apenas nome e
primary. A otimização precisa de ambientes, pontos críticos, posições
candidatas e um catálogo de tipos de sensor com custo, estoque, alcance e
abertura. Também precisa registrar execuções, soluções e configurações manuais
para consulta e comparação. A persistência existente é PostgreSQL no Supabase,
acessado somente pelo backend via PostgREST.

## Decisão

- Representar a residência como um documento `HomeLayout`, validado pelo
  Pydantic (ids únicos, referências existentes, limites de tamanho), e gravá-lo
  como `jsonb` em `securebase_home_layouts`, uma linha por residência.
- Usar concorrência otimista: `PUT /homes/{home_id}/layout` envia a versão
  lida, e uma versão divergente responde `409 LAYOUT_VERSION_CONFLICT`.
- Quando não há layout salvo, devolver o layout-base da maquete
  (`source: template`) com orçamento e custos **vazios**. Avaliar ou otimizar
  exige preenchê-los (`409 LAYOUT_INCOMPLETE`), para que nenhuma métrica seja
  calculada com valores inventados.
- Gravar cada execução em `securebase_optimization_runs`, com uma cópia
  (*snapshot*) do layout usado, a semente e os parâmetros, e suas soluções em
  `securebase_optimization_solutions`. A gravação usa uma única RPC
  (`securebase_create_optimization_run`) para ser atômica.
- Gravar configurações manuais (`securebase_manual_configurations`) só com os
  sensores. As métricas são recalculadas na leitura contra o layout atual. Na
  comparação com uma execução, a configuração é avaliada contra o *snapshot*
  daquela execução.
- Seguir o padrão existente: migration versionada, RLS habilitada, acesso
  revogado de `anon`/`authenticated` e concedido a `service_role`.

## Alternativas consideradas

- **Tabelas normalizadas** (ambientes, pontos, candidatos e tipos): permitem
  consultas por campo, mas o layout é sempre lido e gravado inteiro pela
  interface e validado como um todo. As tabelas aumentariam o número de
  requisições PostgREST e exigiriam transações entre várias tabelas.
- **Gravar métricas da configuração manual:** ficariam desatualizadas quando o
  layout mudasse. Recalcular é barato e garante consistência.

## Consequências

- Mudar o formato do layout exige compatibilidade na validação Pydantic;
  layouts antigos inválidos respondem `503 INVALID_DATABASE_RESPONSE`.
- Execuções continuam reprodutíveis e comparáveis mesmo após o layout mudar,
  graças ao *snapshot*.
- Uma configuração manual pode deixar de ser avaliável se um ponto candidato
  for removido; a API informa o motivo em `evaluation_error`.
