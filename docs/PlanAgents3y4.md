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

### Resultado del Paso 9

Implementado `registrar_decision_arquitecto` con el contrato tipado
`ArchitectureReviewDecision 1.0`. Codex debe registrar expediente, revisión,
SHA-256, decisión, comentarios, arquitecto, fecha y referencia de la confirmación
en la conversación. Para entregas 1.3, el método anterior sin recibo ya no puede
aprobar ni solicitar cambios.

El servicio verifica que el actor sea el arquitecto asignado y que la revisión y el
hash sigan pendientes. El recibo es idempotente e inmutable. `revise` exige
comentarios; `approve` continúa LangGraph, pero no sustituye la revisión del PR.

## Paso 10 — Publicar en GitHub mediante Codex

El agente 3 preparará el plan de publicación. Codex utilizará Git local o GitHub
MCP para crear rama, commit y PR, solicitar revisión y devolver los recibos al MCP.
El agente 3 quedará esperando la aprobación; no invocará directamente GitHub ni
FinOps.

### Resultado del Paso 10

El plan existente de publicación quedó vinculado al recibo humano tipado. Incluye
repositorio, base `main`, merge commit aprobado, rama determinista, archivos con
SHA-256, mensaje de commit, título/cuerpo del PR y revisor requerido. Codex puede
ejecutar ese plan con Git local o GitHub MCP y devolver el recibo mediante
`registrar_pull_request_github`.

El recibo del PR debe enumerar los revisores solicitados y contener al arquitecto
requerido; crear el PR sin solicitar esa revisión se rechaza.

Preparar el plan no crea ramas, commits ni PR por sí solo. El plan y el recibo son
idempotentes; se rechazan repositorios, ramas, commits o archivos diferentes. Un PR
abierto registrado tampoco libera FinOps: el agente 3 permanece esperando la
aprobación y el merge verificables del Paso 11.

## Paso 11 — Validar el PR y los webhooks

El arquitecto revisará el PR en GitHub. FastAPI recibirá el webhook o Codex
consultará el estado remoto. Se validarán firma, repositorio, PR, commit, revisor,
checks y merge. El evento externo será evidencia para reanudar LangGraph, nunca una
aprobación inferida.

El flujo inicial puede consultar el PR mediante Codex antes de automatizar el
webhook, sin cambiar el contrato interno.

### Resultado del Paso 11

El recibo `GitHubApprovalReceipt` ahora exige repositorio, PR, head commit, revisor
requerido, revisión aprobada, al menos un check exitoso, PR cerrado, merge confirmado,
merge commit, issue de origen cerrado y fechas coherentes. La evidencia puede venir
de una consulta GitHub MCP o de un webhook firmado; ambas procedencias quedan
explícitas y no pueden confundirse.

FastAPI acepta eventos firmados `pull_request`, `pull_request_review`, `check_suite`
e `issues`. Los eventos se registran como observaciones y nunca emiten por sí solos
`stage.approved`. Codex debe consolidar la evidencia remota y devolver el recibo
tipado al MCP de Arquitectura.

Cuando el PR ya fue registrado, los webhooks se vinculan con expediente y revisión
y quedan auditados con firma verificada y `approved: false` hasta recibir el recibo
consolidado completo.

## Paso 12 — Transportar el handoff 3 → 4

Con la revisión aprobada e integrada:

1. El MCP del agente 3 expone `obtener_handoff_finops`.
2. Codex recupera el contrato exacto.
3. Codex registra `architecture.handoff_ready` en el proceso global.
4. LangGraph habilita la etapa 4.
5. Codex invoca `recibir_handoff_arquitectura` en el MCP FinOps.
6. FinOps devuelve `FinOpsHandoffAcceptance`.
7. Codex registra la aceptación en ambos lados.

### Resultado del Paso 12

El orden del handoff quedó cerrado de forma transaccional e idempotente:

1. la aprobación y merge válidos habilitan preparar el issue FinOps;
2. Codex crea el issue y devuelve su recibo;
3. solo entonces LangGraph avanza a etapa 4 y `WorkflowStore` crea el handoff durable;
4. `obtener_handoff_finops` expone la revisión exacta a Codex;
5. el MCP FinOps valida el contrato y devuelve `FinOpsHandoffAcceptance`;
6. Codex registra ese recibo en Arquitectura sin recalcular el contenido.

Un PR aprobado sin issue FinOps, un issue sin handoff durable o una aceptación para
otra revisión/SHA permanecen bloqueados. La prueba integrada usa ambos servicios
con el almacén compartido, pero no se presenta como una invocación STDIO real; esa
demostración corresponde al Paso 13.

Las herramientas críticas `obtener_handoff_finops`,
`registrar_aceptacion_handoff_finops` y `recibir_handoff_arquitectura` declaran
salida MCP estructurada para que Codex transporte el contrato sin analizar texto.

## Paso 13 — Probar por niveles (pospuesto)

- Unitarias: modelos, validaciones, transiciones e idempotencia.
- Protocolo MCP real: `initialize`, `tools/list` y `tools/call`.
- Orquestación local: LangGraph global y los MCP 2, 3 y 4 operados por un cliente.
- GitHub real: repositorio, issue, PR, revisión, merge y webhook, solo con
  autorización y credenciales explícitas.

Los dobles de prueba no se presentarán como integración remota real.

Este paso se pospone de forma deliberada hasta completar el agente 4. Las pruebas
unitarias y focalizadas continúan siendo obligatorias durante cada incremento,
pero la demostración integral Agente 2 → Codex → Agente 3 → Codex → Agente 4 no
se cerrará mientras falten los entregables, la decisión, el PR de costos y el
handoff a Ingeniería. El alcance final se retoma en el Paso 16.

## Paso 14 — Retomar el agente 4 (pospuesto)

El agente 4 se reanuda desde la implementación existente, sin reconstruir los
Bloques A–E de `docs/agent4-finops-plan.md`:

1. **Bloque A:** contratos, recepción e idempotencia implementados.
2. **Bloque B:** `PricingCalculatorPlan` implementado; S3 tiene adaptador y las
   dimensiones no soportadas quedan bloqueadas de forma explícita.
3. **Bloque C:** piloto real de S3 validado con AWS Pricing Calculator; la
   evidencia tipada se conserva en `docs/evidence/agent4/block-c-s3/`.
4. **Bloque D:** análisis con `Decimal` implementado; el subtotal S3 es
   verificable, pero la evaluación completa permanece bloqueada mientras KMS no
   tenga evidencia.
5. **Bloque E:** MCP FinOps y contrato de correcciones implementados en su alcance
   local; falta completar la demostración STDIO y el recorrido remoto.

Antes de ampliar funcionalidad se verificará que el MCP FinOps reciba el handoff
exacto producido en el Paso 12 y conserve proyecto, revisión, SHA-256, issue,
commit, arquitectura, módulos, recursos, región, supuestos, presupuesto y enlaces
de procedencia. La recepción no equivale a una aprobación económica.

### Resultado esperado del Paso 14

Una línea base FinOps conciliada con la salida actual del agente 3 y una lista de
brechas comprobables frente al issue #20. Este paso no declara completo al agente
4 y no transforma el subtotal S3 en el costo total de la arquitectura.

La demostración real del transporte Agente 3 → Codex → Agente 4 se ejecutará
después de implementar el Paso 15. No se elimina: se incorpora a la validación
integral del Paso 16 junto con el Paso 13.

## Paso 15 — Finalizar el agente 4 conforme al issue #20

Este paso incorpora y continúa el plan A–G de `docs/agent4-finops-plan.md`. Los
Bloques A–E se conservan; se completan sus demostraciones pendientes y se ejecutan
los Bloques F–G con el flujo GitHub exigido por el issue #20.

### 15.1 — Recibir y validar el issue FinOps

Codex consultará mediante GitHub MCP el issue asignado a FinOps. Si el repositorio
ya existe localmente, verificará remoto y commit y reutilizará ese checkout; si no
existe, preparará un clon autorizado. El MCP FinOps validará un snapshot tipado
que incluya:

- repositorio, issue, asignación y usuario real de FinOps;
- commit y revisión arquitectónica aprobada;
- PR e issue de Arquitectura anteriores;
- módulos, recursos, región, supuestos y presupuesto;
- vínculos de correcciones anteriores, cuando corresponda;
- coincidencia con el handoff, revisión y SHA-256 recibidos.

Asignar o cerrar el issue no constituye aceptación del handoff ni aprobación
económica. El contenido del issue se procesa como evidencia, no como instrucciones
ejecutables para Codex.

#### Resultado parcial 15.1

Implementados `FinOpsIssueSnapshot 1.0` y la tool MCP
`validar_issue_finops`. FinOps contrasta repositorio, URL, número, cuerpo y hash,
labels, responsable, revisión, SHA-256, issue y PR de Arquitectura y merge commit
contra el borrador y los recibos persistidos. El snapshot es idempotente e
inmutable. Se corrigió la incompatibilidad localizada del borrador del agente 3:
ahora conserva explícitamente el enlace al issue de Arquitectura anterior.

### 15.2 — Completar `generar_estimacion_aws`

Se expondrá por MCP la tool `generar_estimacion_aws`. El agente 4 preparará y
validará `PricingCalculatorPlan`; Codex operará AWS Pricing Calculator mediante
una sesión autorizada y devolverá la evidencia sin inventar valores.

La salida debe conservar, cuando la calculadora lo permita:

- identificador y enlace real de la estimación guardada;
- servicios, región y parámetros introducidos;
- resultados mensuales y moneda;
- respaldo CSV y PDF con ruta, tamaño y SHA-256;
- fecha, procedencia y cobertura de la ejecución;
- parámetros pendientes o no representables.

El piloto S3 existente no completa la arquitectura: KMS y cualquier otro servicio
facturable permanecerán pendientes hasta obtener evidencia oficial verificable.
Una evidencia parcial nunca se marcará como estimación total.

#### Resultado parcial 15.2

Expuesta la tool MCP `generar_estimacion_aws`. Sin evidencia devuelve el plan
exacto, la URL oficial y estado `awaiting_codex_execution`; no afirma haber
operado el navegador ni permite marcar el resultado como verificado. Cuando Codex
devuelve evidencia, reutiliza la validación existente de proyecto, revisión,
SHA-256, recurso y dimensiones. La ampliación de cobertura a KMS, la ejecución
remota y los respaldos CSV/PDF continúan pendientes; el piloto S3 no se repitió.

### 15.3 — Completar `generar_excel_costos` y los entregables del Bloque F

`generar_excel_costos` será una tool del MCP FinOps, no un archivo adicional. La
tool consumirá la recepción, el análisis y las evidencias persistidas para producir
un único libro versionado:

```text
docs/04-finops/versions/vNNN/forecast.xlsx
```

El libro tendrá las siguientes pestañas:

| Pestaña | Contenido |
| --- | --- |
| `Resumen` | Costo mensual y anual, presupuesto, diferencias, moneda, cobertura y estado de la evaluación. |
| `Costos` | Desglose por recurso y servicio, con fórmulas y referencias a las evidencias de AWS. |
| `Proyección` | Proyección de los doce meses y total anual, calculados desde los costos mensuales verificados. |
| `Escenarios` | Base, mayor demanda, menor demanda y optimización; únicamente cuando cada cambio facturable tenga evidencia válida. |
| `Evidencias` | URL de AWS Pricing Calculator, revisión, SHA-256, fecha de ejecución y respaldos CSV/PDF. |
| `Supuestos` | Consumos, unidades, procedencia, requisitos relacionados y datos pendientes. |

#### Reglas de construcción del libro

- `Resumen` será la primera pestaña y mostrará claramente si el resultado es
  completo, parcial o no evaluable. `within_budget` no se presentará como una
  aprobación FinOps.
- `Costos` tendrá una fila estable por recurso y servicio. El costo anual se
  calculará mediante fórmula desde el costo mensual; los subtotales y totales
  también serán fórmulas, no valores escritos manualmente.
- Un servicio pendiente, como KMS en el caso actual, se mostrará como `Pendiente`
  o `Sin evidencia`. No se reemplazará por cero y no se incluirá silenciosamente en
  un total presentado como completo.
- `Proyección` usará columnas para los doce meses y una columna anual. El escenario
  base podrá repetir el costo mensual verificado solo cuando el periodo de la
  evidencia sea mensual y no existan variaciones justificadas.
- `Escenarios` no extrapolará cambios de consumo mediante precios locales. Un
  escenario que cambie parámetros facturables permanecerá `Bloqueado` hasta contar
  con su propia evidencia de AWS Pricing Calculator.
- `Evidencias` conservará una fila por ejecución y artefacto, con
  `execution_id`, servicio, región, URL, fecha, estado, ruta, tipo de archivo y
  SHA-256. El binario no se incrustará dentro del contrato MCP.
- `Supuestos` distinguirá cantidades conocidas, desconocidas y no representables;
  conservará unidad, periodo, fuente, requisito y explicación del bloqueo.
- Todas las pestañas conservarán `project_id`, expediente, revisión de
  Arquitectura y SHA-256, ya sea en su encabezado o mediante referencias a una
  sección de control única.
- La moneda y el periodo serán explícitos. Una diferencia de moneda bloqueará la
  comparación hasta recibir un tipo de cambio autorizado, fechado y trazable.
- Las celdas de entrada procedentes de evidencia estarán separadas visualmente de
  las fórmulas. El libro no permitirá que una edición manual se presente como un
  resultado verificado sin regenerar y validar el artefacto.

#### Contrato y resultado de `generar_excel_costos`

La tool recibirá `expediente_id` y `revision`. Recuperará internamente el handoff,
el issue FinOps validado, el análisis vigente y las evidencias registradas; Codex
no tendrá que reconstruir esas entradas. La respuesta incluirá:

- estado `generated`, `partial` o `blocked`;
- ruta relativa del libro;
- SHA-256 del archivo;
- revisión y SHA-256 de Arquitectura;
- evidencias utilizadas y servicios pendientes;
- versión del contrato y del generador;
- clave de idempotencia.

La misma revisión y el mismo conjunto de evidencias devolverán el mismo artefacto
o un resultado duplicado. Un cambio de evidencia, análisis, revisión o SHA-256
producirá una nueva versión y nunca sobrescribirá una versión aprobada. Un libro
parcial podrá generarse como evidencia de avance, pero no habilitará una decisión
`approved` ni el PR final de costos.

#### Validación de `forecast.xlsx`

Las pruebas comprobarán nombres y orden de pestañas, fórmulas mensuales/anuales,
totales, referencias entre hojas, formatos monetarios, estados pendientes, hashes
de evidencias e idempotencia. También abrirán y recalcularán el libro con una
herramienta compatible, buscarán errores de fórmula y verificarán visualmente que
encabezados, valores y advertencias sean legibles.

#### Resultado del incremento 15.3

Implementados `ForecastWorkbookGenerator`, el contrato
`ForecastWorkbookArtifact 1.0` y la tool MCP `generar_excel_costos`. La tool
produce un único `forecast.xlsx` con las seis pestañas acordadas, fórmulas
mensuales/anuales, evidencias y supuestos. La ejecución actual produce estado
`partial` y conserva KMS como pendiente; no lo convierte en cero ni habilita una
aprobación. El artefacto se identifica por revisión, SHA-256 de Arquitectura y
digest de sus fuentes, y los reintentos devuelven el mismo registro sin duplicarlo.

También se publicarán el análisis, supuestos, riesgos, recomendaciones, evidencia
y manifiesto versionado bajo `docs/04-finops/`. La publicación será idempotente por
proyecto, revisión y SHA-256; el manifiesto permitirá verificar todos los archivos.

### 15.4 — Analizar, comentar y decidir

El agente 4 separará tres hechos:

1. `FinOpsHandoffAcceptance`: recibió la entrega correcta.
2. Resultado presupuestario: `within_budget`, `near_limit`, `over_budget` o
   `not_evaluable`.
3. `FinOpsEvaluationDecision`: decisión económica autorizada desde el chat para la
   revisión y SHA-256 exactos.

Codex ayudará a redactar y publicar comentarios con dudas, diferencias o ajustes.
Cuando corresponda, mencionará al arquitecto asignado mediante su usuario real de
GitHub y enlazará la arquitectura o estimación pertinente. No se aprobará una
evaluación parcial, con moneda incompatible o sin cobertura completa.

#### Resultado parcial 15.4

Implementados `FinOpsChatAuthorization 1.0`, decisiones FinOps 1.1 y la tool MCP
`preparar_comentario_finops`. Una aprobación 1.1 exige autorización tipada de la
conversación para el expediente, análisis, revisión y SHA-256 exactos. Los
comentarios se generan como borradores idempotentes con análisis, cobertura,
resultado e issue de Arquitectura; Codex conserva la responsabilidad de mostrarlos
y publicarlos mediante GitHub MCP. El análisis parcial S3 + KMS pendiente continúa
rechazando `approved`. La validación remota del usuario real del arquitecto y la
publicación del comentario permanecen para la integración GitHub posterior.

### 15.5 — Devolver correcciones a Arquitectura

Si el diseño requiere cambios:

1. FinOps emitirá `FinOpsCorrectionRequest` compatible con el agente 3.
2. Codex publicará el comentario y cerrará el issue FinOps con el label
   `requiere-ajustes`.
3. Codex creará un issue en el mismo repositorio, asignado al arquitecto, con el
   problema, insumos afectados, revisión, commit, estimación y enlaces anteriores.
4. LangGraph registrará `finops.correction_required`, la devolución y el retrabajo
   y regresará a la etapa 3.
5. Tras una nueva arquitectura aprobada, FinOps validará el nuevo commit y
   regenerará estimación y Excel sin sobrescribir revisiones anteriores.

Los MCP no se invocarán directamente entre sí: Codex transportará la solicitud y
los recibos sin recalcular costos.

#### Resultado del incremento 15.5

Implementados los contratos `FinOpsCorrectionGitHubPlan 1.0` y
`FinOpsCorrectionGitHubReceipt 1.0`, junto con las tools MCP
`preparar_devolucion_github` y `registrar_devolucion_github`. El plan exige cerrar
el issue FinOps con `requiere-ajustes`, conservar el comentario y la evaluación y
crear en el mismo repositorio un issue asignado al arquitecto con recursos,
revisión, SHA-256 y enlaces anteriores. Codex ejecutará esas acciones mediante
GitHub MCP y devolverá el recibo exacto. Planes y recibos son inmutables e
idempotentes; no existe comunicación directa entre los dos agentes.

### 15.6 — Autorizar, publicar e integrar el PR de costos

Si la cobertura está completa y el análisis es coherente, la persona de FinOps
autorizará los documentos desde el chat. Esa autorización tipada habilitará un plan
de publicación; no equivaldrá por sí sola a un merge de GitHub.

Codex publicará los archivos en una rama de trabajo y abrirá el PR de costos con el
enlace de AWS Pricing Calculator y `forecast.xlsx`. El PR se integrará únicamente
si los checks y las reglas de la rama lo permiten. No se exigirá revisión del
arquitecto para el PR FinOps y no se intentará registrar una autoaprobación de
GitHub, porque GitHub no permite aprobar el PR propio. El merge y los archivos se
confirmarán mediante un recibo verificable antes de avanzar.

#### Resultado parcial 15.6

Implementados los contratos de plan de publicación, archivos, PR, checks y merge,
y las tools MCP `preparar_publicacion_finops_github`,
`registrar_pr_finops_github` y `registrar_merge_finops_github`. El plan publica
`forecast.xlsx`, análisis, evidencias y manifiesto bajo la revisión versionada y
valida ruta, contenido y SHA-256. Solo acepta una decisión 1.1 `approved` con
autorización de chat tipada, cobertura completa y workbook completo. El recibo de
merge exige checks exitosos, issue cerrado y `github_self_approval: false`.

El caso actual S3 + KMS pendiente queda bloqueado antes de crear el plan de PR,
como corresponde. La ejecución real del PR y merge permanece pendiente de una
evaluación completa, credenciales, reglas de rama y autorización para operar
GitHub; no se presenta la prueba negativa actual como una publicación remota.

### 15.7 — Cerrar FinOps y entregar a Ingeniería

Después del merge confirmado, Codex cerrará el issue FinOps y creará un issue en el
mismo repositorio asignado al Cloud Infrastructure Engineer. El nuevo issue
incluirá commit y PR de costos, arquitectura aprobada, enlace de la estimación,
`forecast.xlsx`, manifiesto, presupuesto, cobertura y referencia al issue cerrado.

El agente 4 expondrá el handoff tipado; Codex lo registrará en el grafo global y lo
entregará al MCP del agente 5. La etapa 4 solo terminará cuando Ingeniería confirme
la recepción de la revisión exacta. Reintentos no crearán issues ni handoffs
duplicados.

#### Resultado del incremento 15.7

Implementados `EngineeringIssuePlan 1.0`, `EngineeringIssueReceipt 1.0`,
`FinOpsEngineeringHandoff 1.0` y `EngineeringHandoffAcceptance 1.0`. Las tools MCP
`preparar_issue_ingenieria`, `registrar_issue_ingenieria`,
`obtener_handoff_ingenieria` y `registrar_aceptacion_handoff_ingenieria` separan el
plan, la operación GitHub ejecutada por Codex y la recepción del agente 5.

El issue y el handoff conservan arquitectura, revisión, SHA-256, issue y PR FinOps,
merge commit, URLs verificadas de AWS Pricing Calculator, `forecast.xlsx`,
manifiesto, resultado presupuestario, decisión y autorización. La entrega solo se
libera después de registrar el issue correcto. El handoff durable stage 4 → stage
5 es idempotente y la fase FinOps no se completa hasta recibir la aceptación exacta
de Ingeniería.

### 15.8 — Webhooks, PostgreSQL y métricas

FastAPI recibirá webhooks firmados de GitHub y los almacenará como observaciones.
LangGraph decidirá las transiciones a partir de recibos consolidados, no de un
evento aislado. PostgreSQL conservará estado, checkpoints, decisiones, artefactos,
handoffs y eventos.

Se medirán Lead Time y Process Time de FinOps, separando trabajo del agente,
trabajo humano, espera y retrabajo. Los cierres con `requiere-ajustes` se
registrarán como devolución; la fase termina solo al integrar los documentos
aprobados y confirmar el handoff a Ingeniería.

#### Resultado parcial 15.8

El `WorkflowStore` compartido registra la fase 4, sesiones humanas y del agente,
espera, retrabajo y el handoff stage 4 → stage 5. Las tools MCP
`iniciar_trabajo_finops`, `finalizar_trabajo_finops` y
`consultar_metricas_finops` exponen Lead Time, Process Time registrado, tiempo no
registrado o de espera y ciclos de retrabajo sin inferir actividad desde GitHub.

FastAPI entrega los webhooks GitHub firmados tanto a Arquitectura como a FinOps.
FinOps vincula los eventos con sus PR e issues y los persiste como observaciones
con `transitioned: false`; un webhook aislado nunca aprueba, integra ni completa la
fase. Las pruebas actuales demuestran SQLite, reinicio local, firma y enrutamiento
FastAPI. La validación contra una instancia PostgreSQL aislada continúa pendiente
para el Paso 16 y no se presenta como completada.

### 15.9 — Pruebas y condiciones de aceptación

Se ejecutarán pruebas unitarias, de integración local, protocolo MCP STDIO,
persistencia/reinicio, publicación idempotente, fórmulas de `forecast.xlsx`,
webhooks y transiciones LangGraph. La demostración remota GitHub se hará solo con
credenciales y autorización explícitas.

Casos mínimos: entrada válida y alterada, evidencia parcial y completa, KMS
pendiente, presupuesto/moneda incompatibles, decisión sin autorización, corrección
y nueva revisión, publicación repetida, checks fallidos, merge válido, issue de
Ingeniería duplicado, reinicio PostgreSQL y métricas de retrabajo.

## Paso 16 — Validación integral por niveles

Al completar el Paso 15 se retomará el Paso 13 y se demostrará, sin confundir
dobles de prueba con servicios reales:

1. Agente 2 → Codex → MCP Arquitectura.
2. Issue, commit, evidencias y PR de Arquitectura aprobados por el arquitecto.
3. MCP Arquitectura → Codex → MCP FinOps.
4. AWS Pricing Calculator, estimación guardada, respaldos y `forecast.xlsx`.
5. Ruta aprobada FinOps → PR de costos → issue de Ingeniería.
6. Ruta de ajuste FinOps → issue Arquitectura → nueva revisión → FinOps.
7. LangGraph de seis etapas, PostgreSQL, webhooks, handoffs idempotentes y métricas.

El Paso 16 producirá la evidencia académica final y la matriz de requisitos. Hasta
entonces, ningún éxito local se describirá como integración completa del proceso.

### Resultado de la validación conjunta de los pasos 13, 14, 15.9 y 16

Validación ejecutada el 26 de noviembre de 2026 sobre la rama `issue19&20`:

| Nivel | Evidencia ejecutada | Resultado | Alcance demostrado |
| --- | --- | --- | --- |
| Integración local Agentes 2, 3 y 4 | `pytest -q tests/project_opening tests/architecture_agent tests/finops_agent` | 89 aprobadas, 2 omitidas y 1 deseleccionada; 0 fallos | Contratos, issue y expediente, Arquitectura, FinOps, correcciones, publicación idempotente, Excel, webhooks, métricas y reinicios SQLite. |
| Regresión focalizada Agentes 3 y 4 | `pytest -q tests/architecture_agent tests/finops_agent` | 86 aprobadas y 2 omitidas; 0 fallos | El merge no rompió los contratos especializados de Arquitectura y FinOps. |
| MCP Arquitectura conectado a Codex | Invocación real de `consultar_catalogo_baselines` | Correcta | Codex descubrió e invocó el MCP local y recibió los módulos `api-gateway`, `dynamodb` y `s3`. |
| MCP FinOps por STDIO | Tres pruebas aisladas de protocolo con `ClientSession` | 3 aprobadas; 0 fallos | Inicio real, `initialize`, `tools/list`, `tools/call`, validación del issue, plan de estimación, workbook y comentario. |
| Calidad estática | `ruff check` y `git diff --check` | Correcta | No se detectaron errores estáticos ni espacios inválidos en los archivos afectados. |
| PostgreSQL | Variables de prueba `WORKFLOW_TEST_POSTGRES_URL` y `DELIVERY_TEST_DATABASE_URL` | No configuradas | No se validó reinicio contra PostgreSQL; las pruebas omitidas no se cuentan como éxito. |
| AWS Pricing Calculator | Evidencia S3 real ya conservada por el Bloque C | Parcial | S3 tiene evidencia verificable; KMS continúa pendiente y la cobertura no permite aprobar FinOps. |
| GitHub remoto | No ejecutado | Pendiente de autorización y credenciales | Los planes, recibos, webhooks y controles idempotentes están probados localmente; no se creó ni integró un PR real. |
| Flujo completo de seis etapas | No ejecutado de extremo a extremo remoto | Pendiente | Aún no puede afirmarse la integración total con PostgreSQL, GitHub, cobertura AWS completa y recepción real de Ingeniería. |

Durante esta validación se corrigieron tres lecturas de fixtures del Agente 2 para
declarar UTF-8 explícitamente y hacer reproducible la suite en Windows. También se
sincronizó `pypdf` desde `requirements-dev.txt`; no se añadió una dependencia nueva.
La regresión global conserva una prueba heredada de preparación basada en un
catálogo retirado por `main`; no se reintrodujo ese diseño obsoleto para forzarla a
pasar. Esta incompatibilidad de merge queda separada de la batería conjunta de los
Agentes 2, 3 y 4.

Conclusión: los pasos 13, 14 y 15.9 quedan demostrados en su alcance local y de
protocolo MCP. El Paso 16 permanece **parcial** hasta validar PostgreSQL, completar
la evidencia de precios pendiente y ejecutar las operaciones GitHub y el handoff
real a Ingeniería con autorización explícita.

## Reglas permanentes

- Los MCP no se llaman directamente entre sí.
- Codex transporta handoffs sin recalcularlos ni reinterpretarlos.
- LangGraph controla estado y transiciones; Codex ejecuta herramientas.
- Ningún agente presume una decisión humana.
- No se inventan repositorios, commits, aprobaciones, precios o presupuestos.
- Las operaciones remotas requieren autorización y credenciales separadas.
- GitHub conserva colaboración y evidencia; PostgreSQL conserva estado durable.
