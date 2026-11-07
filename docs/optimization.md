# Otimização da posição de sensores (NSGA-II)

Este documento descreve o modelo matemático, os parâmetros do algoritmo, a API
e as limitações do laboratório de otimização. As decisões arquiteturais estão
nas ADRs [0007](./adr/0007-nsga2-com-pymoo.md),
[0008](./adr/0008-modelo-da-residencia-e-persistencia-da-otimizacao.md) e
[0009](./adr/0009-integracao-da-otimizacao-com-a-maquete-3d.md).

Código: `src/modules/service/optimization_model.py` (modelo),
`optimization_nsga2.py` (algoritmo), `optimization_service.py` (orquestração) e
`optimization_template.py` (layout-base da maquete).

## 1. Dados de entrada (layout)

Todas as coordenadas usam as unidades da cena 3D da maquete (altura total de
2,05; X/Z centralizados; Y = 0 no piso da base).

| Elemento | Campos principais |
|---|---|
| Ambiente | `id`, `glb_node`, `floor_y`, `height`, retângulo `min_xz`/`max_xz`, `visible_room_ids` |
| Ponto crítico `j` | ambiente, posição `x_j`, importância `w_j ∈ {1..5}` |
| Ponto candidato `c` | ambiente, posição `x_c`, tipos permitidos, custo extra de instalação `e_c`, direção opcional |
| Tipo de sensor `t` | custo unitário `u_t`, custo de instalação `i_t`, estoque `S_t`, alcance `r_t`, abertura `φ_t`, confiabilidade `ρ_t` |
| Global | orçamento `B`, limiar de cobertura `τ` (padrão 0,8) |

O layout-base (`source: template`) traz ambientes, pontos e tipos medidos na
maquete, com `B`, `u_t` e `i_t` **vazios**. Sem esses valores, avaliar ou
otimizar responde `409 LAYOUT_INCOMPLETE`.

## 2. Modelo de detecção

Para um sensor do tipo `t` instalado no candidato `c` e um ponto crítico `j`:

```
p_cj = ρ_t  se  (amb(j) = amb(c)  ou  amb(j) ∈ visible_room_ids(amb(c)))
             e  ‖x_j − x_c‖ ≤ r_t
             e  ângulo_horizontal(x_j − x_c, d_c) ≤ φ_t / 2
       0    caso contrário
```

`d_c` é a direção informada no candidato ou, na falta dela, a direção do
candidato ao centro do retângulo do ambiente. Com `φ_t = 360` o sensor é
omnidirecional.

Supondo detecções independentes, a probabilidade de o ponto `j` ser detectado
pela configuração `x` é:

```
c_j(x) = 1 − Π_{genes ativos g} (1 − p_gj)
```

O ponto conta como **coberto** quando `c_j ≥ τ`.

## 3. Objetivos

| Objetivo | Definição | Sentido |
|---|---|---|
| Cobertura | `C(x) = |{ j : c_j(x) ≥ τ }| / J` | maximizar |
| Custo | `K(x) = Σ_g x_g · (u_t(g) + i_t(g) + e_c(g))` | minimizar |
| Vulnerabilidade residual | `V(x) = Σ_j w_j (1 − c_j(x)) / Σ_j w_j` | minimizar |

O pymoo minimiza `F = (−C, K, V)`. Cobertura e vulnerabilidade são
correlacionadas, mas não equivalentes: a cobertura conta pontos acima do
limiar sem peso, e a vulnerabilidade pondera a probabilidade de falha pela
importância de cada ponto.

## 4. Restrições

```
g_0(x) = K(x) − B              ≤ 0      (orçamento)
g_t(x) = Σ_{g: tipo t} x_g − S_t ≤ 0    (estoque de cada tipo)
no máximo um sensor por ponto candidato  (garantido pelo repair)
tipo permitido no candidato              (garantido pela codificação)
```

Somente soluções com todas as restrições satisfeitas são devolvidas. A
viabilidade é recalculada após o NSGA-II, sem depender do estado interno da
biblioteca. A configuração vazia é sempre viável (custo 0) e aparece na
fronteira como extremo de custo mínimo.

## 5. NSGA-II

- **Indivíduo:** vetor binário `x ∈ {0,1}^G`. Cada gene corresponde a um par
  (candidato, tipo permitido); `G ≤ 1000`.
- **População inicial:** amostragem binária aleatória (`BinaryRandomSampling`)
  seguida do *repair*.
- **Seleção:** torneio binário pelo critério do NSGA-II (posto de dominância e
  *crowding distance*), com dominância por restrições de Deb: uma solução
  viável vence uma inviável, e entre inviáveis vence a de menor violação.
- **Crossover:** dois pontos (`TwoPointCrossover`), probabilidade 0,9. Os genes
  de um mesmo candidato são adjacentes, o que preserva blocos.
- **Mutação:** bit-flip com probabilidade `min(0,5; 1/G)` por gene.
- **Repair:** quando um candidato fica com mais de um tipo ativo, mantém um ao
  acaso (gerador semeado pela execução).
- **Sobrevivência:** ordenação não dominada rápida e *crowding distance*
  (`RankAndCrowding`), com eliminação de duplicatas.
- **Resultado:** a primeira frente não dominada das soluções viáveis da
  população final, sem duplicatas, ordenada por custo crescente. **A API não
  marca nenhuma solução como a melhor.** A escolha é feita na interface, pelo
  critério que a pessoa usuária seleciona. O botão **Aplicar melhor opção**
  aplica a primeira solução por esse critério; o padrão, **Equilibrada**,
  prefere as soluções que atingem `coverage_threshold` e, entre elas, a de
  menor custo (desempate: menor vulnerabilidade). Se nenhuma atinge o limiar,
  vence a de maior cobertura.

| Parâmetro | Padrão | Limites |
|---|---|---|
| `population_size` | 60 | 10–200 |
| `generations` | 100 | 1–300 |
| `seed` | aleatória (retornada) | 0 – 2³¹−1 |

Com a mesma semente e o mesmo layout, o resultado é idêntico.

## 6. API

Todas as rotas exigem `Authorization: Bearer <access_token>`. Membros da
residência podem ler, avaliar e comparar; primary e master também podem salvar
o layout, executar e gravar configurações manuais. O contrato completo está em
[`api.yml`](./api.yml) e em `/docs`.

| Método | Caminho (`/api/v1/homes/{home_id}`) | Permissão | Observações |
|---|---|---|---|
| GET | `/layout` | membro | Layout salvo ou layout-base (`source`) |
| PUT | `/layout` | primary/master | `version` lida; `409 LAYOUT_VERSION_CONFLICT` |
| POST | `/configurations/evaluate` | membro | Métricas reais, sem gravar |
| POST | `/optimization-runs` | primary/master | `Idempotency-Key`; `201` com a fronteira |
| GET | `/optimization-runs` | membro | `limit` (≤ 100) e `offset` |
| GET | `/optimization-runs/{run_id}` | membro | Snapshot do layout e soluções |
| GET | `/optimization-runs/{run_id}/solutions/{solution_id}` | membro | Detecção por ponto |
| POST | `/optimization-runs/{run_id}/compare` | membro | Manual × soluções, dominância |
| GET | `/manual-configurations` | membro | Métricas recalculadas no layout atual |
| POST | `/manual-configurations` | primary/master | `Idempotency-Key` |
| DELETE | `/manual-configurations/{configuration_id}` | primary/master | `204` |

Erros específicos (`application/problem+json`):

| `code` | Status | Quando |
|---|---|---|
| `LAYOUT_REQUIRED` | 409 | Avaliar, otimizar ou salvar configuração sem layout salvo |
| `LAYOUT_INCOMPLETE` | 409 | Orçamento ou custos dos tipos usados vazios |
| `LAYOUT_VERSION_CONFLICT` | 409 | Versão enviada difere da salva |
| `INVALID_SENSOR_PLACEMENT` | 422 | Tipo não permitido no candidato, ou id inexistente |
| `VALIDATION_ERROR` | 422 | Layout ou parâmetros inválidos (ids duplicados, referências quebradas, limites) |
| `OPTIMIZATION_BUSY` | 503 | Duas otimizações já em execução no processo |
| `OPTIMIZATION_TIMEOUT` | 503 | Execução acima de 60 s |
| `OPTIMIZATION_RUN_NOT_FOUND`, `SOLUTION_NOT_FOUND`, `MANUAL_CONFIGURATION_NOT_FOUND` | 404 | Recurso inexistente nesta residência |

A comparação informa, para cada solução, `delta_* = solução − manual` e a
relação de dominância de Pareto. `manual_is_dominated` é verdadeiro quando
alguma solução calculada é ao menos tão boa em todos os objetivos e melhor em
pelo menos um.

## 7. Executar e testar

Backend (na pasta `secure_base_back-end`, com o Supabase local iniciado conforme
[`INSTRUCOES_BD.md`](../INSTRUCOES_BD.md)):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
supabase migration up --local
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m main
```

Testes:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_optimization_model.py tests/test_optimization_api.py
```

`test_optimization_model.py` verifica as métricas contra cálculos feitos à mão,
as restrições, a validação do layout, a reprodutibilidade e compara a fronteira
do NSGA-II com uma enumeração exaustiva em uma instância pequena.
`test_optimization_api.py` cobre permissões, versionamento, idempotência,
isolamento entre residências, avaliação, configurações manuais e comparação.

No frontend, abra **Otimização** no menu lateral, revise o layout, informe
orçamento e custos, salve e execute. Na aba **Pareto**, **Aplicar melhor
opção** carrega a solução escolhida como configuração manual; para guardá-la,
salve-a com um nome na aba **Sensores**.

## 8. Hipóteses e limitações

- **Geometria simplificada:** não há oclusão por paredes ou móveis. A
  visibilidade entre ambientes é declarada em `visible_room_ids`, e a abertura
  só considera o plano horizontal.
- **Detecção binária por alcance:** dentro do alcance e do cone, a
  probabilidade é constante (`ρ_t`); não decai com a distância.
- **Independência:** falhas de sensores diferentes são independentes.
- **Sensores de contato** (vibração e inclinação) são modelados com alcance
  pequeno (0,15) junto ao ponto; o modelo não distingue arrombamento de
  abertura.
- **Escala da maquete:** alcances e posições estão em unidades da maquete. O
  alcance do PIR (1,75) e a abertura (110°) vêm do simulador
  (`src/sim/world.ts`), não de uma ficha técnica.
- **Importâncias e posições do layout-base** são um ponto de partida para
  revisão, não um levantamento de risco.
- **Execução síncrona:** o timeout interrompe a espera, mas não a thread de
  cálculo, que termina normalmente. Limites de parâmetros mantêm execuções
  curtas.
- **Fronteira aproximada:** o NSGA-II é uma heurística; em instâncias grandes,
  a fronteira devolvida pode não ser a fronteira ótima completa.
