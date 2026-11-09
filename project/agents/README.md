# Agentes del proceso

Los agentes con runtime independiente viven en su carpeta con código, instrucciones,
modelos, dependencias y pruebas locales propias. Los agentes implementados como
grafos del backend se registran aquí y se ejecutan mediante su worker, sin duplicar código.

| Número | Nombre | Identificador | Responsabilidad | Etapa de negocio |
| --- | --- | --- | --- | --- |
| 1 | [Calendar Assistant](1.%20calendar%20assistant/README.md) | `calendar_assistant` | Agendar, reagendar y cancelar reuniones verificadas | Engagement Manager: agendamiento |
| 2 | [Meeting Assistant](2.%20meeting%20assistant/README.md) | `meeting_assistant` | Registrar decisión y cola en PostgreSQL, crear desde template y entregar el issue al arquitecto | Dirección: apertura de proyecto |

El agente de preparación ejecutiva se implementa en `backend/app/preparation/`,
con estado, nodos y grafo propios, y se ejecuta mediante `make workflow`. Su MCP
está en `backend/app/mcp_server.py`. La apertura de la etapa 2 está implementada en
`backend/app/project_opening/`, con su MCP propio y LangGraph. La reunión de
dirección y su evaluación previa quedan pendientes. Las etapas 3–6 mantienen sus
contratos de coordinación.

El número en el nombre de la carpeta identifica al agente; no forma parte de un
paquete Python ni cambia su identificador. Se mantiene `1. calendar assistant`.

Las seis secciones de [issues.md](../../issues.md) son etapas de negocio; una
puede necesitar varios agentes. La preparación ejecutiva del primer issue está
en `backend/app/preparation`, ejecutada por el worker de LangGraph; no pertenece
al agente de agenda. `backend/app/workflow` coordina los contratos de las seis etapas.

Los siguientes agentes se incorporan cuando exista una implementación. Cada uno
agrupa sus reglas en `src/domain`, adaptadores en `src/integrations` y herramientas
en `src/tools`. La conversación vive en `prompts/` y la identidad y modelos en
`agent.json`. Los datos de clientes, OTP y correo transaccional pertenecen al
[backend](../backend/README.md); la oficina virtual pertenece al
[frontend](../frontend/README.md).

Consultar [la arquitectura](../../docs/architecture.md) para las dependencias y
el [README principal](../../README.md) para los comandos locales.
