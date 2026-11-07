# ADR 0007 — Otimização de sensores com NSGA-II (pymoo)

- **Status:** Aceita.
- **Data:** 2026-11-06.

## Contexto

O laboratório de otimização precisa sugerir posições de sensores equilibrando
três objetivos conflitantes: maximizar a cobertura dos pontos críticos,
minimizar o custo e minimizar a vulnerabilidade residual. As restrições são o
orçamento e o estoque de cada tipo de sensor. Não existe uma solução única
ótima: o resultado esperado é uma fronteira de Pareto para a pessoa usuária
escolher a alternativa segundo seu próprio critério.

O backend é Python/FastAPI e não tinha bibliotecas numéricas. Também não há
fila de tarefas nem workers separados.

## Decisão

- Usar o algoritmo **NSGA-II** da biblioteca **pymoo** (0.6.2), com:
  - representação binária, em que cada gene é um par (ponto candidato, tipo
    permitido);
  - amostragem binária aleatória, crossover de dois pontos (p = 0,9) e
    mutação bit-flip (p por gene = 1/n);
  - *repair* próprio, que garante no máximo um sensor por ponto candidato;
  - orçamento e estoque como restrições de desigualdade `g ≤ 0`, tratadas pela
    dominância por restrições do pymoo (Deb).
- Manter o modelo matemático (objetivos, restrições e detecção) em
  `optimization_model.py`, puro e vetorizado com numpy. O mesmo código avalia
  as soluções do NSGA-II e as configurações manuais.
- Recalcular a viabilidade e a não dominância ao final, sem depender do estado
  interno da biblioteca, e devolver **apenas** soluções viáveis e mutuamente
  não dominadas, sem eleger uma "melhor".
- Executar de forma síncrona no processo da API, em thread
  (`asyncio.to_thread`), com limites de população (≤ 200), gerações (≤ 300),
  genes (≤ 1000), timeout de 60 s e no máximo duas execuções simultâneas por
  processo. A semente é gravada para permitir reprodução.

## Alternativas consideradas

- **DEAP:** mais leve (depende só de numpy) e oferece `selNSGA2`, mas não trata
  restrições nativamente; exigiria penalidades ou seleção própria.
- **Implementação própria do NSGA-II:** contraria a orientação de não
  reimplementar componentes complexos sem necessidade e aumenta o risco de
  erros sutis em ordenação não dominada e *crowding distance*.
- **Fila de tarefas (Celery/RQ) com execução assíncrona:** adequada para
  instâncias grandes, mas introduz infraestrutura nova (broker, workers). Com
  os limites definidos, uma execução típica leva poucos segundos.

## Consequências

- A imagem de produção fica maior: pymoo traz numpy, scipy, matplotlib e
  outras dependências, fixadas em `requirements*.txt`.
- Execuções ocupam CPU do processo da API. O timeout interrompe a espera, mas
  não a thread, que continua até terminar; os limites de parâmetros mantêm
  esse tempo curto. Se o uso crescer, a execução deve migrar para workers
  dedicados em uma ADR futura.
- Os testes comparam a fronteira encontrada com uma enumeração exaustiva em
  uma instância pequena, verificando o algoritmo de ponta a ponta.
