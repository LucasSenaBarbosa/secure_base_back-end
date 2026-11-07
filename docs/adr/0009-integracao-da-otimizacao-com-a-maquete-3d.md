# ADR 0009 — Integração da otimização com a maquete 3D

- **Status:** Aceita.
- **Data:** 2026-11-06.

## Contexto

O frontend já renderiza a maquete `casa_smart_premium_v02.glb` com
`HouseV2` (React Three Fiber). O GLB tem nós nomeados por ambiente
(`02_Interiores/Sala`, `Cozinha`, `Suite`, `Estar_Superior` e
`01_Arquitetura/Garagem`, `Varanda`, `Escada`). O `Lab` atual é ligado ao
estado do simulador (`useSim`): câmera, foco, raio-X e firmware.

## Decisão

- Criar uma página separada, **Otimização**, que reutiliza `HouseV2` sem alterar
  o `Lab`. `HouseV2` recebe um parâmetro opcional para forçar o raio-X
  (paredes translúcidas), de modo que os pontos internos fiquem visíveis.
- Usar no layout as **mesmas unidades da cena 3D**. O layout-base foi medido a
  partir das caixas delimitadoras dos nós do GLB, com a mesma centralização e
  escala aplicadas por `buildHouseV2`, e cada ambiente guarda o nome do nó em
  `glb_node`.
- Sensores só podem ser colocados em **pontos candidatos** do layout. Os
  candidatos aparecem como marcadores clicáveis; não há posicionamento livre
  sobre a malha.
- Manter o estado da página em um store próprio
  (`src/optimization/store.ts`), separado de `useSim`, e mostrar sempre se a
  configuração exibida é **manual** ou **calculada** (execução e semente).

## Alternativas consideradas

- **Estender o `Lab`:** misturaria simulação de firmware com planejamento e
  acoplaria a otimização a `useSim`.
- **Posicionamento livre por raycast na malha:** exigiria validar paredes e
  superfícies; os pontos candidatos já expressam as limitações físicas.
- **Calcular as caixas dos ambientes em tempo real a partir do GLB:** as caixas
  dos nós de interiores refletem móveis e se sobrepõem (a cozinha fica dentro
  da caixa da sala); o layout precisa de retângulos revisáveis.

## Consequências

- Se o GLB mudar de escala ou posição, o layout-base precisa ser medido de
  novo; layouts salvos não são ajustados automaticamente.
- A cena da otimização não reproduz efeitos do simulador (chuva, gás, LEDs),
  que não fazem parte do planejamento.
