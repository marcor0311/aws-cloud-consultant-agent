# Plan de integración — Agentes 3 y 4 mediante Codex y MCP

## Arquitectura acordada

LangGraph conserva el estado del proceso, valida las transiciones entre las seis
etapas y coordina las revisiones internas. Cada agente es un servicio independiente
expuesto mediante un MCP local. Los MCP no se llaman directamente entre sí.

Codex actúa como cliente y operador inteligente: consulta el estado del proceso,
invoca las herramientas MCP, transporta handoffs sin reinterpretarlos, opera Git,
GitHub y AWS Pricing Calculator cuando corresponda, y presenta las decisiones a la
persona autorizada. La autoridad humana no se delega al modelo: el arquitecto
aprueba Arquitectura y FinOps registra su decisión económica conforme a las reglas
del proyecto.

```text
LangGraph global
    determina etapa y transición permitida
                 ↓
Codex
    conversa, razona y ejecuta herramientas autorizadas
                 ↓
MCP local especializado
    ejecuta y valida las capacidades del agente independiente
                 ↓
LangGraph especializado
    conserva revisiones, interrupciones y estado interno
                 ↓
Persona autorizada
    aprueba o solicita cambios sobre la revisión exacta
```

FastAPI expone estado y recibe eventos externos. PostgreSQL conserva procesos,
checkpoints, handoffs, eventos y tiempos. GitHub conserva issues, commits, PR y
revisiones como evidencia colaborativa.

## Paso 0 — Estabilizar el merge

1. Confirmar que el merge de `main` terminó y no quedan conflictos.
2. Sincronizar las dependencias incorporadas desde `main`.
3. Ejecutar pruebas focalizadas de los agentes 1, 2 y 3.
4. Comprobar que sus servidores MCP arrancan y exponen herramientas.
5. Registrar por separado cualquier fallo preexistente.

**Resultado:** línea base limpia y reproducible antes de cambiar contratos.

### Resultado del Paso 0

- Merge de `main` confirmado, sin conflictos pendientes.
- Dependencias del backend sincronizadas; se incorporaron `reportlab` y
  `playwright`.
- Agente 1: `1 passed` al ejecutar su entorno bloqueado sin instalar el proyecto.
  El comando directo `uv run --locked pytest` descubre un defecto preexistente de
  empaquetado editable: `setuptools` busca `src/calendar_assistant`, mientras el
  código utiliza `src` como paquete raíz.
- Agentes 2 y 3 y composición: `55 passed, 2 skipped, 1 deselected`.
- Comprobaciones MCP focalizadas de Arquitectura: `2 passed`.
- Ruff pasa en los archivos y áreas afectadas.
- Se corrigieron tres regresiones de integración/portabilidad descubiertas tras el
  merge: composición MCP sin servicio de preparación, bloqueo de worker con
  `msvcrt` en Windows y validación POSIX de permisos OAuth limitada a POSIX.

El Paso 0 queda completo. El defecto de empaquetado del agente 1 se conserva como
pendiente independiente porque no afecta su contrato ni las pruebas ejecutadas.

## Paso 1 — Definir los tres niveles de estado

Documentar sin modificar todavía los contratos:

- Estado global: etapas 1–6, iteración, revisión y retrabajo.
- Estado especializado del agente 3: recepción, validación, revisión humana,
  publicación, PR, aprobación y handoff.
- Estado externo: issue, rama, commit, PR, revisión y merge.

No se equipararán estados diferentes: un issue asignado no es un handoff aceptado,
una aprobación interna no es un PR integrado y un PR integrado no demuestra que
FinOps recibió la entrega.

### Resultado del Paso 1

Se adopta la siguiente separación contractual:

| Nivel | Autoridad | Estados actuales relevantes | Qué demuestra |
| --- | --- | --- | --- |
| Proceso global | `app/workflow/` | `awaiting_meeting`, `awaiting_transcript`, `preparing`, `awaiting_deliverable`, `awaiting_review`, `completed`, `declined`, `cancelled` | Etapa 1–6, iteración, revisión y transición permitida |
| Apertura del agente 2 | `app/project_opening/` | `queued`, `board_approved`, `repository_ready`, `documents_ready`, `awaiting_initial_structure_merge`, `initial_structure_merged`, `awaiting_architect_access`, `issue_ready`, `delivered` | Creación y conciliación del proyecto, PR inicial, issue y handoff |
| Arquitectura del agente 3 | `app/architecture/` | `awaiting_review`, `blocked_for_finops_inputs`, `ready_for_finops`, `finops_changes_requested` | Revisión arquitectónica, aprobación exacta y posibilidad de entregar a FinOps |
| FinOps del agente 4 | `app/finops/` | recepción `received`; planes `ready`, `partial` o `blocked`; evidencia `verified`, `partial` o `unverified`; análisis `ready_for_decision`, `partial` o `blocked` | Recepción, cobertura y estado económico, separados de la decisión autorizada |
| GitHub externo | recibos tipados | issue, commit, PR `open`, review `approved`, issue `closed`, merge commit | Evidencia remota; nunca sustituye por sí sola una transición global |

La identidad de referencia para la adaptación es el repositorio local:

```text
C:\Users\USUARIO\Documents\GitHub\MultiAgent\aws-cloud-consulting-project-nike-01-lindora-run
```

Su remoto verificado es
`https://github.com/aws-cloud-consulting-group/aws-cloud-consulting-project-nike-01-lindora-run.git`
y su `main` actual apunta a
`a050fa04bcd0bc3649c2593e3a5555c35e4f5f41`, merge del PR inicial #1.
La entrega contiene cinco evidencias discovery y un acta JSON/Markdown bajo
`docs/02-board/`. Es un ejemplo 1.2 legado con votación simulada declarada, no la
única forma admitida para aperturas nuevas con `direction_decision`.

#### Invariantes entre niveles

- `project_opening.status == delivered` demuestra que el agente 2 creó su handoff;
  no demuestra que el agente 3 lo aceptó.
- `architecture.status == awaiting_review` demuestra que existe una revisión; no
  demuestra aprobación humana ni publicación.
- La aprobación interna del arquitecto no basta cuando `github_required=True`:
  debe existir un `GitHubApprovalReceipt` válido para el mismo plan, revisión y SHA.
- `architecture.status == ready_for_finops` permite preparar la entrega; FinOps debe
  devolver después su aceptación tipada.
- `FinOpsIntake.operational_status == received` no equivale a una decisión económica.
- `within_budget` no equivale a `approved`.

El Paso 1 queda completo. No se modificaron modelos de handoff.

## Paso 2 — Definir eventos del LangGraph global

El grafo global recibirá eventos tipados, sin inspeccionar documentos internos:

- `project_opening.completed`
- `architecture.accepted`
- `architecture.revision_requested`
- `architecture.published`
- `architecture.handoff_ready`
- `finops.accepted`
- `finops.correction_required`
- `finops.approved`

Cada evento conservará identificador, expediente, etapa, iteración, revisión,
SHA-256, actor, origen, evidencias y referencia al handoff. Codex obtiene los datos
del MCP correspondiente y registra el evento; LangGraph decide si la transición es
válida.

### Resultado del Paso 2

El grafo global ya tiene un contrato estable en `ProcessEvent`. No se ampliará con
nombres especializados en esta etapa. Los hitos de dominio se conservan como
eventos de auditoría y Codex o el servicio autorizado los traduce a uno de los
eventos globales existentes.

| Hito de dominio | Evento global existente | Precondición global | Resultado global | Evidencia mínima |
| --- | --- | --- | --- | --- |
| Reunión terminada | `meeting.completed` | Etapa 1, `awaiting_meeting` | `awaiting_transcript` | Recibo de reunión |
| Paquete del agente 1 preparado | `preparation.ready` interno | Etapa 1, preparación activa | `awaiting_review` | Revisión, SHA y artefacto |
| Paquete del agente 1 aprobado | `preparation.approved` interno | Etapa 1, revisión exacta | Etapa 2, `awaiting_review` | Revisión, SHA y aprobación |
| Dirección aprueba y agente 2 completa la apertura | `stage.approved` | Etapa 2, revisión exacta | Etapa 3, `awaiting_deliverable` | Decisión, repo, commit, PR inicial, issue y handoff |
| Dirección rechaza | `stage.rejected` | Etapa 2, revisión exacta | `declined` | Decisión y motivo certificados |
| Agente 3 produce arquitectura revisable | `deliverable.ready` | Etapa 3, `awaiting_deliverable` | `awaiting_review` | Revisión, SHA y artefactos |
| Arquitectura aprobada y PR integrado | `stage.approved` | Etapa 3, revisión exacta | Etapa 4, `awaiting_deliverable` | Aprobación, commit, PR, review y merge |
| FinOps produce evaluación completa | `deliverable.ready` | Etapa 4, `awaiting_deliverable` | `awaiting_review` | Evaluación, evidencia de precios, revisión y SHA |
| FinOps autoriza la evaluación | `stage.approved` | Etapa 4, revisión exacta | Etapa 5, `awaiting_deliverable` | Decisión y autorización trazable |
| FinOps solicita corrección arquitectónica | `stage.changes_requested` | Etapa 4, revisión exacta | Etapa 3, nueva iteración | Solicitud tipada y evaluación FinOps |

Los nombres `project_opening.completed`, `architecture.published`,
`architecture.handoff_ready`, `finops.accepted` y
`finops.correction_required` pueden mantenerse como eventos detallados en
`WorkflowStore`, pero no serán nuevos valores de `ProcessEvent`. Esta decisión evita
dos máquinas de estados globales incompatibles.

#### Autoridad para emitir eventos

- Codex consulta el proceso y transporta la intención o los recibos.
- El MCP especializado valida la revisión y genera el resultado tipado.
- El backend asigna el actor autenticado y registra el evento.
- El worker vuelve a validar etapa, iteración, revisión, SHA e idempotencia antes de
  reanudar LangGraph.
- Un webhook solo crea evidencia observada; no emite `stage.approved` por sí mismo.

#### Brechas confirmadas

1. La ruta exitosa actual del agente 2 completa su fase y crea el handoff, pero no
   sincroniza de forma explícita el `stage.approved` de la etapa 2 en el proceso
   global. Se resolverá al formalizar su salida en el Paso 3.
2. El agente 3 ya sincroniza `deliverable.ready` y `stage.approved`, pero solo libera
   la transición cuando existe aprobación GitHub si `github_required=True`.
3. FinOps persiste recepción, análisis, decisión y corrección, pero todavía no
   sincroniza sus resultados con el proceso global. Se completará al retomar el
   agente 4.

El Paso 2 queda completo como definición contractual. La implementación se hará en
los pasos de cada frontera, sin comunicación directa entre MCP.

## Paso 3 — Formalizar la salida del agente 2

El agente 2 expondrá una herramienta de solo lectura, tentativamente
`obtener_handoff_arquitectura`, que devuelva exclusivamente información persistida
y conciliada:

- Expediente y proyecto.
- Repositorio y commit aprobado.
- PR inicial y merge commit.
- Issue de Arquitectura y arquitecto asignado.
- Presupuesto y decisión de Dirección.
- Archivos aprobados, manifiesto y hashes.
- Recibo del handoff persistido.

El agente 2 no llamará al agente 3. Codex transportará el resultado exacto.

### Resultado del Paso 3

Implementado el contrato de transporte `ArchitectureProjectDelivery 1.3` y la
herramienta MCP de solo lectura `obtener_handoff_arquitectura`. La salida se arma
exclusivamente desde el registro de apertura y los recibos persistidos: repositorio,
commit publicado, PR inicial integrado, issue, arquitecto, paquete aprobado,
presupuesto, decisión y handoff. La ruta de un checkout local no forma parte del
transporte porque depende del entorno donde Codex ejecuta el agente 3.

El recibo del issue ahora conserva también el SHA-256 de su cuerpo. Esto permitirá
comparar en el Paso 6 el snapshot recuperado de GitHub sin confiar únicamente en la
URL o en la asignación. La herramienta no llama al MCP de Arquitectura ni acepta el
handoff en nombre del arquitecto.

## Paso 4 — Ajustar el contrato de entrada del agente 3

Después de observar la salida real del paso anterior se decidirá si corresponde
crear `ArchitectureProjectHandoff 1.3`. Se mantendrá compatibilidad con 1.1 y 1.2.

El contrato distinguirá explícitamente:

- `direction_decision`: decisión directa de Dirección confirmada y persistida.
- `board_record`: acta de junta con sus evidencias.

También conservará repositorio, commit, PR inicial, issue, arquitecto, revisión del
paquete, manifiesto, presupuesto, `request_sha256`, condición simulada y recibo del
handoff. Una decisión del agente 2 nunca aprobará automáticamente la arquitectura.

### Resultado del Paso 4

Implementada la recepción compatible del contrato 1.3, conservando sin cambios la
lectura de `ArchitectureProjectHandoff` 1.1 y 1.2. La decisión usa una unión
discriminada entre `direction_decision` y `board_record`; una simulación de junta y
una declaración de firmas verificadas por la fuente quedan explícitas y no se
convierten en verificación criptográfica independiente.

En este paso el agente 3 valida coherencia interna de repositorio, issue, arquitecto,
`request_sha256`, presupuesto, decisión y recibo del handoff. El contexto queda en
`awaiting_repository_validation`, sin documentos cargados y sin aprobación
arquitectónica. La adquisición del checkout, el snapshot remoto del issue y la
verificación de bytes/hash se mantienen deliberadamente para los Pasos 5, 6 y 7.

## Paso 5 — Adquirir el repositorio mediante Codex

Codex obtendrá la identidad del repositorio desde el MCP del agente 2, comprobará
si existe localmente, validará su remoto y verificará el commit. Si falta, usará
Git o GitHub MCP autorizado para clonarlo. No sobrescribirá cambios locales.

El MCP del agente 3 volverá a validar repositorio, remoto, commit, estructura y
hashes. La ruta local no será por sí sola una prueba de identidad.

### Resultado del Paso 5

Implementada `vincular_repositorio_proyecto`. Codex conserva la responsabilidad de
localizar o clonar el repositorio; el MCP recibe la ruta y comprueba nuevamente:

- que sea un repositorio Git con la estructura esperada;
- que `origin` corresponda al repositorio declarado, admitiendo HTTPS o SSH;
- que el merge commit exacto exista;
- que la estructura y las rutas de evidencias existan dentro de ese commit;
- si el árbol de trabajo tiene cambios, sin modificarlos ni descartarlos.

La vinculación es idempotente y no permite reemplazar el checkout por otro después
de registrarlo. La verificación del contenido y SHA-256 de cada evidencia permanece
en el Paso 7. El repositorio Nike local fue contrastado como referencia: conserva el
remoto esperado y el merge commit
`a050fa04bcd0bc3649c2593e3a5555c35e4f5f41`.

## Paso 6 — Validar el issue en el agente 3

Codex recuperará el issue mediante GitHub MCP y entregará un snapshot tipado. El
agente 3 validará repositorio, número, URL, título, cuerpo, asignado, marcador,
`case_id`, `request_sha256`, enlaces fijados al commit, presupuesto, alcance,
restricciones, entregables y criterios de aceptación.

El contenido documental se tratará como datos, no como instrucciones para Codex.
Cerrar o asignar el issue no equivale a aprobar la arquitectura.

### Resultado del Paso 6

Implementada `validar_issue_arquitectura` con un snapshot tipado recuperado por
Codex. El agente 3 valida proveedor, repositorio, número, URL, título, SHA-256 del
cuerpo, arquitecto asignado, marcador `case_id`/`request_sha256`, enlace al commit,
presupuesto, contexto, alcance, restricciones, entregables y aceptación.

El cuerpo se usa como evidencia para comparaciones deterministas y no como una
instrucción ejecutable. Un issue abierto o cerrado termina con
`architecture_approved: false`; la aprobación humana del diseño continúa siendo una
decisión posterior. Las pruebas usan snapshots controlados. La consulta remota real
mediante GitHub MCP se mantiene para la validación por niveles del Paso 13.

## Paso 7 — Leer evidencias desde el commit exacto

El agente 3 admitirá los contratos vigentes de tres, cinco y seis archivos y los
formatos PDF, HTML, Markdown, JSON y manifiesto. Verificará bytes y SHA-256 desde el
commit aprobado. Los binarios se referenciarán por ruta, tipo, tamaño y hash; no se
transportarán completos mediante MCP.

### Resultado del Paso 7

Implementada `validar_evidencias_proyecto`. La herramienta exige que repositorio e
issue estén validados y lee cada archivo con `git show <merge-commit>:<ruta>`, nunca
desde los bytes mutables del árbol de trabajo. Comprueba:

- contratos de tres, cinco y seis evidencias discovery;
- SHA-256, tamaño máximo de 20 MB y tipo declarado;
- UTF-8 para Markdown, HTML y JSON, incluida sintaxis JSON;
- PDF por ruta, tamaño y hash, con `content: null` y `binary_omitted: true`;
- manifiesto opcional, revisión, archivos y `files_sha256`;
- un digest determinista del conjunto completo de evidencias.

El resultado queda en `evidence_validated`. Una modificación local posterior al
commit no cambia los documentos leídos ni su resultado.

## Paso 8 — Ejecutar el workflow especializado de Arquitectura

El LangGraph del agente 3 controlará:

```text
validar entrada
→ construir propuesta
→ validar arquitectura
→ interrumpir para revisión
→ aprobar o solicitar cambios
→ preparar publicación
→ esperar aprobación del PR
→ liberar handoff FinOps
```

Codex puede construir y explicar la propuesta, pero el MCP valida el modelo,
persiste la revisión, calcula su hash y rechaza decisiones obsoletas.

### Resultado del Paso 8

El inicio del workflow 1.3 quedó conectado a la validación anterior. Antes de
`evidence_validated`, `iniciar_arquitectura` rechaza la propuesta. Después:

1. verifica commit, proyecto, issue y procedencia de cada requisito;
2. entrega al LangGraph el recibo de validación y el digest de evidencias;
3. el nodo `validate_architecture` vuelve a validar `ArchitecturePackage` y módulos;
4. genera los artefactos deterministas de la revisión 1;
5. se interrumpe en `architect_review` con revisión y SHA-256 exactos.

El paso no registra `approve` ni `revise`: esa autoridad continúa reservada al
arquitecto en el Paso 9. Los flujos anteriores sin contrato 1.3 mantienen su
compatibilidad mediante `input_validation: not_required`.

## Paso 9 — Registrar la decisión del arquitecto

Codex presentará requisitos, servicios, diagrama, riesgos, módulos, supuestos y
consumos. El arquitecto decidirá `approve` o `revise`. Codex registrará esa decisión
mediante el MCP para la revisión y SHA-256 exactos. LangGraph continuará o abrirá
una nueva revisión.

## Paso 10 — Publicar en GitHub mediante Codex

El agente 3 preparará el plan de publicación. Codex utilizará Git local o GitHub
MCP para crear rama, commit y PR, solicitar revisión y devolver los recibos al MCP.
El agente 3 quedará esperando la aprobación; no invocará directamente GitHub ni
FinOps.

## Paso 11 — Validar el PR y los webhooks

El arquitecto revisará el PR en GitHub. FastAPI recibirá el webhook o Codex
consultará el estado remoto. Se validarán firma, repositorio, PR, commit, revisor,
checks y merge. El evento externo será evidencia para reanudar LangGraph, nunca una
aprobación inferida.

El flujo inicial puede consultar el PR mediante Codex antes de automatizar el
webhook, sin cambiar el contrato interno.

## Paso 12 — Transportar el handoff 3 → 4

Con la revisión aprobada e integrada:

1. El MCP del agente 3 expone `obtener_handoff_finops`.
2. Codex recupera el contrato exacto.
3. Codex registra `architecture.handoff_ready` en el proceso global.
4. LangGraph habilita la etapa 4.
5. Codex invoca `recibir_handoff_arquitectura` en el MCP FinOps.
6. FinOps devuelve `FinOpsHandoffAcceptance`.
7. Codex registra la aceptación en ambos lados.

## Paso 13 — Probar por niveles

- Unitarias: modelos, validaciones, transiciones e idempotencia.
- Protocolo MCP real: `initialize`, `tools/list` y `tools/call`.
- Orquestación local: LangGraph global y los MCP 2, 3 y 4 operados por un cliente.
- GitHub real: repositorio, issue, PR, revisión, merge y webhook, solo con
  autorización y credenciales explícitas.

Los dobles de prueba no se presentarán como integración remota real.

## Paso 14 — Retomar el agente 4

1. Finalizar la validación STDIO del MCP FinOps.
2. Recibir el handoff real del agente 3.
3. Mantener KMS pendiente mientras no exista evidencia verificable.
4. Publicar documentos, manifiesto, evidencia y `forecast.xlsx`.
5. Abrir y validar el PR FinOps.
6. Registrar la decisión y entregar a Ingeniería mediante Codex y el grafo global.

## Reglas permanentes

- Los MCP no se llaman directamente entre sí.
- Codex transporta handoffs sin recalcularlos ni reinterpretarlos.
- LangGraph controla estado y transiciones; Codex ejecuta herramientas.
- Ningún agente presume una decisión humana.
- No se inventan repositorios, commits, aprobaciones, precios o presupuestos.
- Las operaciones remotas requieren autorización y credenciales separadas.
- GitHub conserva colaboración y evidencia; PostgreSQL conserva estado durable.
