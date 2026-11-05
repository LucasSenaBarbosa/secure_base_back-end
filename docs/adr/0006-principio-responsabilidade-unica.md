# ADR 0006 — Princípio da Responsabilidade Única

- **Status:** Aceita.
- **Data:** 2026-11-05.

## Contexto

O backend precisa manter o código organizado para que mudanças em uma
responsabilidade não afetem partes sem relação com ela. O Princípio da
Responsabilidade Única (SRP, *Single Responsibility Principle*) orienta que
cada módulo tenha uma responsabilidade principal e um motivo coerente para
mudar.

## Decisão

- Aplicar o SRP separando o backend por camadas, conforme a
  [ADR 0005](./0005-organizacao-layer-first.md).
- Manter cada camada focada em seu papel:
  - `routes/` recebe e configura as requisições HTTP;
  - `controller/` coordena a operação e encaminha o trabalho ao serviço;
  - `service/` implementa as regras e os fluxos de negócio;
  - `schemas/` define e valida os formatos de dados;
  - `repository/` encapsula o acesso aos dados.
- Manter o nome da funcionalidade nos arquivos de cada camada, como
  `homes_routes.py`, `homes_controller.py` e `homes_service.py`, para relacionar
  os componentes sem misturar suas responsabilidades.
- Considerar essa separação uma aplicação intencional e consistente do SRP na
  arquitetura do backend.

## Consequências

- Cada parte do sistema tem um papel claro, facilitando localizar onde uma
  mudança deve ser feita e mantendo as responsabilidades organizadas.
- Alterações no transporte HTTP, nas regras de negócio, na validação ou no
  acesso a dados podem ser tratadas na camada correspondente.
- O fluxo continua integrado entre camadas: rotas e controllers encaminham
  operações, serviços aplicam as regras e o repositório realiza as operações
  de dados necessárias.
