# Repository guide

Current scope: local application architecture. Do not add deployment infrastructure
unless requested. Read docs/architecture.md before changing component boundaries.

- project/backend: FastAPI, client records, OTP and transactional email. Python
  imports start with app; tests and requirements live in this component.
- project/agents/1. calendar assistant: agent 1. Keep this folder name. Read its
  AGENTS.md. Domain rules must not import LiveKit, MCP, Google or backend code.
- project/frontend: virtual-office interface and static assets.
- project/.env: non-sensitive local settings and CLOUD_CONSULTANT_SECRETS_DIR.
  Credentials and sessions live outside Git in ~/.config/aws-cloud-consultant-agent/dev/.
  project/data is private local state. Preserve credentials, clients and data.
  See config/local-secrets.example/README.md before changing credential paths.

Use make backend, make agent and make frontend from the repository root to run
components in separate terminals. make test runs local tests; make check runs
Python lint and formatting. Agent tests use offline mocks and simulated transcripts.
Do not add or run cloud simulations or automated real calls; real inference
requires explicit user authorization for each execution.
Keep only essential integration journeys and end-to-end checks. Reuse existing
coverage rather than adding unit cases, parameter matrices or architecture-shape
assertions. Run the affected component once; expand only for a concrete failure.
The test inventory is the five integration journeys in docs/testing.md plus the
optional voice E2E and PostgreSQL journey. Do not add standalone adapter, UI,
format, or edge-case tests; extend a journey only for a real integration need.
`make test` is the small offline integration suite. `make test-e2e` and
`make test-postgres` are on-demand, not mandatory steps for routine edits.

Keep API paths, OTP protections, appointment rules and client codes intact during
structural changes. Update imports, local commands, CI paths and documentation
when moving files. Do not import the numbered agent folder as a Python package.

# Flujo de trabajo autorizado

- Antes de crear una rama nueva, solicita autorización explícita al usuario. Una instrucción explícita de crearla ya constituye esa autorización.
- La autorización para implementar una tarea no implica autorización para crear otra rama sin consultar.
- Antes de editar, comprueba la rama y el estado del repositorio. Implementa únicamente en la rama de trabajo autorizada; no implementes cambios en main.
- Conserva cualquier trabajo existente del usuario. No descartes cambios para cambiar de rama.
- No publiques ramas, abras PRs ni hagas merges sin una instrucción del usuario que lo autorice.
- Las instrucciones de los AGENTS.md de subdirectorios siguen aplicando dentro de su alcance.
