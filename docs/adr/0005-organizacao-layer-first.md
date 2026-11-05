# ADR 0005 — Organização do backend por camadas (Layer-first)

- **Status:** Aceita.
- **Data:** 2026-11-05.

## Contexto

O backend contém funcionalidades como autenticação, usuários e residências.
Cada funcionalidade envolve responsabilidades técnicas distintas, como expor
rotas HTTP, coordenar requisições, aplicar regras de negócio, validar dados e
acessar o banco.

Há duas formas comuns de organizar esse código. Em uma organização por
funcionalidade (*feature-first*), cada funcionalidade contém seus próprios
arquivos de rotas, controllers, serviços e schemas. Em uma organização por
camadas (*layer-first*), arquivos com a mesma responsabilidade ficam juntos,
com a funcionalidade identificada no nome do arquivo.

## Decisão

- Organizar o código em `src/modules/` principalmente por responsabilidade
  técnica:
  - `routes/`: endpoints e contratos HTTP;
  - `controller/`: coordenação entre as rotas e os serviços;
  - `service/`: regras de negócio;
  - `schemas/`: modelos de validação e dados de entrada e saída;
  - `repository/`: acesso a dados.
- Identificar a funcionalidade no nome dos arquivos, como
  `homes_routes.py`, `homes_controller.py` e `homes_service.py`.
- Manter separadas as responsabilidades entre as camadas; a organização não
  implica que cada camada tenha de implementar lógica para toda funcionalidade.
- Tratar essa decisão como organização interna do backend, não como parte do
  contrato HTTP/API consumido pelos clientes.

## Alternativas consideradas

- **Organizar primeiro por funcionalidade (*feature-first*):** cada pasta, como
  `homes/`, reuniria rotas, controller, serviço e schemas da funcionalidade.
  Não foi escolhida para a estrutura atual, que prioriza agrupar componentes
  pela responsabilidade técnica.

## Consequências

- É fácil localizar componentes por tipo de responsabilidade e visualizar as
  camadas arquiteturais presentes no backend.
- Uma mudança que atravesse todas as partes de uma funcionalidade pode exigir
  navegar por várias pastas; nomes consistentes ajudam a localizar os arquivos
  relacionados.
- A estrutura por camadas não torna a arquitetura inerentemente melhor ou pior
  que a organização por funcionalidade. Se o crescimento do sistema dificultar
  a navegação de ponta a ponta por funcionalidade, a organização poderá ser
  reavaliada em uma ADR futura.
