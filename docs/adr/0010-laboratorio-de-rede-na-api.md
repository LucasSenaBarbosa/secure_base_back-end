# ADR 0010 — Laboratório de rede calculado pela API

- **Status:** Aceita.
- **Data:** 2026-11-08.

## Contexto

O simulador da casa roda no navegador e trata o enlace entre o aplicativo e o
ESP32 como perfeito. A disciplina de telecomunicações pede estudar o que
acontece com a comunicação sob falhas e ataques (jamming, queda de WAN, antena
falsa).

## Decisão

- Calcular o cenário no **backend**, em um modelo puro e determinístico pela
  semente (`link_simulation_model.py`), seguindo as camadas da ADR 0005.
- Guardar cada execução em `securebase_link_simulations`, por residência, com
  o resultado em `jsonb`, acessível só pelo `service_role`.
- Permitir que qualquer membro da residência execute e leia simulações: o
  recurso é de estudo e não altera a configuração da casa. O `POST` exige
  `Idempotency-Key`.
- Devolver no mesmo resultado as métricas **sem defesas**, com a mesma semente,
  para que a comparação venha da API.
- Deixar no frontend só a animação e a aplicação do resultado aos comandos da
  casa (`LinkCondition`), que por padrão é `null` e não altera o simulador.
- Não incluir a tabela nova em `is_ready`: o laboratório é opcional e não deve
  tirar a API de prontidão se a migration ainda não tiver sido aplicada.

## Alternativas consideradas

- **Tudo no navegador:** dispensaria a API, mas perderia histórico, autorização
  por residência e resultados reproduzíveis.
- **Simulador de rede completo (ns-3, GNS3):** mais fiel, porém pesado para
  rodar por requisição e fora do objetivo didático da aplicação.

## Consequências

- Os valores de latência e perda são ilustrativos e estão versionados por
  `MODEL_VERSION`; o resultado não prevê o desempenho de uma rede real.
- Nenhum sinal de rádio ou tráfego real é gerado.
- O histórico não tem limpeza automática; cada linha ocupa poucos KB.
