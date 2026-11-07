# Desarrollo local de AWS Cloud Consultant Agent

Sistema de apoyo para una consultora de arquitectura AWS. La implementación
actual incluye **Calendar Assistant (agente 1)**, clientes y OTP, preparación con
revisión humana, un workflow LangGraph para las seis etapas y la oficina virtual.

## Estructura

```text
project/
├── backend/
│   ├── app/
│   │   ├── main.py / api/        # FastAPI y autenticación HTTP
│   │   ├── bootstrap.py          # Composición compartida
│   │   ├── worker.py             # Entrada y bucle del worker
│   │   ├── mcp_server.py         # Herramientas MCP
│   │   ├── clients/              # Registro de clientes
│   │   ├── verification/         # Servicio OTP y schemas
│   │   ├── notifications/        # Correo OTP y plantilla
│   │   ├── workflow/             # Proceso de seis etapas y runtime de tareas
│   │   ├── preparation/          # Grafo, nodos y servicios de preparación
│   │   ├── persistence/          # SQL, checkpoints y exclusión local
│   │   ├── integrations/         # Proveedores y mocks existentes
│   │   ├── demos/                # Demostraciones existentes
│   │   ├── cli/                  # Comandos administrativos y lanzadores
│   │   └── core/                 # Configuración común
│   ├── fixtures/
│   └── tests/
├── agents/
│   └── 1. calendar assistant/
│       ├── src/                  # Reglas, integraciones y herramientas de voz
│       ├── prompts/
│       ├── demos/                # Runner ficticio del SDK de voz
│       ├── tests/
│       └── agent.json
├── frontend/
│   ├── office-dashboard.html
│   ├── src/                      # JS y CSS
│   ├── assets/                   # Recursos estáticos
│   └── tests/
├── data/                         # Estado local privado
├── generated/                    # Exportaciones y ejecuciones de demos
├── secrets/                      # Credenciales privadas
└── .env                          # Configuración local única
```

[Arquitectura y reglas de dependencia](architecture.md).
[Registro al cierre de llamada y webhook de Calendar](calendar-integration.md).

## Desarrollo local

Requisitos: Python 3.10 o posterior para el backend, Python compatible con el
lockfile del agente, `uv`, LiveKit CLI y Node.js para las pruebas de la interfaz.

En una instalación nueva, copiar `project/.env.example` a `project/.env` y
completar la configuración. No reemplazar un `.env` existente.

```sh
make setup-backend
make setup-agent
```

Desde la raíz, abrir una terminal por componente:

```sh
make backend
```

```sh
make agent
```

```sh
# Requiere WORKFLOW_ENABLED=1; usa el mismo WORKFLOW_MODE y directorio que API/MCP.
make workflow
```

```sh
make frontend
```

La API usa `http://127.0.0.1:8000`, y la oficina virtual se abre en
`http://127.0.0.1:8765/office-dashboard.html`. El agente debe usar ese mismo
puerto del backend en `CALENDAR_ACCESS_URL`.

```sh
make test
make check
```

Los tests locales usan datos y proveedores ficticios, incluidos transcripts
simulados. No hay simulaciones cloud ni llamadas reales automatizadas en las
pruebas o en CI. La inferencia real sigue bloqueada por defecto.

## Documentación

- [Backend: clientes, OTP y correo](../project/backend/README.md)
- [Registro y responsabilidades de agentes](../project/agents/README.md)
- [Agente 1: Calendar Assistant](../project/agents/1.%20calendar%20assistant/README.md)
- [Oficina virtual](../project/frontend/README.md)
- [Proceso de consultoría y contexto académico](process.md)
- [Trabajo pendiente por etapa](../issues.md)

La orquestación usa LangGraph directamente y SQLite local. API, worker, MCP y voz
son procesos separados. Las etapas 2–6 esperan entregables y decisiones explícitas
de sus responsables; sus agentes especializados siguen pendientes. PostgreSQL
cuenta con adaptadores y una prueba opcional, sin infraestructura de despliegue.
