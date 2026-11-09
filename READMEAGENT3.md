# Agente 3 — Cloud Architecture Agent

## Propósito

El Cloud Architecture Agent corresponde al issue #19 y asiste al Cloud Solutions
Architect durante la etapa 3 del proceso de consultoría. Recibe los requisitos y
la aprobación de Dirección, propone una arquitectura AWS, consulta el catálogo de
módulos baseline, documenta decisiones y prepara los insumos que necesita FinOps.

El agente **no genera Terraform**, no ejecuta `terraform apply`, no despliega
infraestructura y no necesita credenciales AWS para su funcionamiento actual.
La generación y validación de Terraform corresponde al agente 5.

## Estado actual

La implementación disponible es un primer incremento funcional. Incluye el
contrato, las validaciones, el grafo LangGraph, la persistencia local, la revisión
humana, las herramientas MCP y el handoff hacia la etapa 4. Todavía no satisface
todo el alcance del issue #19.

### Implementado

- Contrato `ArchitecturePackage` estricto y versionado con Pydantic.
- Requisitos arquitectónicos con procedencia.
- Región y ambiente AWS.
- Recursos, dependencias y supuestos de dimensionamiento.
- Selección de módulos baseline fijados a un commit.
- Validación de versión candidata, perfil y estado de aprobación del módulo.
- Registro explícito de módulos que todavía no existen.
- ADRs con alternativas y trade-offs.
- Controles de seguridad y referencias a políticas como código.
- Riesgos, preguntas abiertas y supuestos iniciales de costos.
- Contrato económico versionado con presupuesto conocido o desconocido.
- Dimensiones de consumo tipadas, unidades validadas y trazabilidad a requisitos.
- Bloqueo explícito del handoff cuando faltan insumos para FinOps.
- Diagrama de arquitectura en Mermaid.
- Generación de documentos Markdown y JSON.
- Grafo LangGraph con revisión humana mediante `interrupt()`.
- Solicitud de cambios y creación de revisiones posteriores.
- Aprobación protegida mediante número de revisión y SHA-256.
- Persistencia de checkpoints y artefactos.
- Handoff de Arquitectura hacia FinOps.
- Retorno estructurado FinOps → Arquitectura con revisiones inmutables.
- Lectura de entregas del agente 2 fijadas a un commit del repo de proyecto.
- Publicación local versionada bajo `docs/03-architecture/`.
- Historial consultable de correcciones, aprobaciones y handoffs.
- Idempotencia por identificador de corrección y número de revisión.
- Avance del workflow principal de la etapa 3 a la etapa 4.
- Servidor MCP dedicado para Codex.
- Instrucciones de repositorio para orientar el razonamiento de Codex.
- Demostración local y pruebas automatizadas sin conexiones externas.
- Compatibilidad del bloqueo local con Windows y sistemas Unix.

### Flujo implementado

```text
Requisitos y antecedentes
        ↓
Codex consulta el catálogo mediante MCP
        ↓
Codex construye ArchitecturePackage
        ↓
El backend valida contrato, módulos y dependencias
        ↓
LangGraph pausa para revisión del arquitecto
        ↓
   ┌───────────────┴────────────────┐
   ↓                                ↓
Solicitar cambios                Aprobar
   ↓                                ↓
Nueva revisión             Handoff ready_for_finops
                                    ↓
                          Workflow pasa a etapa 4
                                    ↓
                    Corrección estructurada de FinOps
                                    ↓
                 Nueva revisión y nueva aprobación humana
```

Codex proporciona el razonamiento del agente. El servidor MCP no inventa el
diseño: valida, versiona, persiste y protege la aprobación de la propuesta
construida por Codex a partir de los requisitos disponibles.

Codex también orquesta la frontera entre los agentes 3 y 4. El agente 3 no llama
al agente 4: expone un contrato económico tipado, vigente y aprobado. Codex debe
recuperarlo y entregarlo sin recalcular ni reinterpretar costos al MCP de FinOps.

## Herramientas MCP

El servidor MCP registrado en Codex se llama `aws_architecture` y utiliza
transporte STDIO. Expone únicamente las herramientas de Arquitectura:

| Herramienta | Responsabilidad |
| --- | --- |
| `consultar_catalogo_baselines` | Lee módulos, perfiles, versiones y estados reales del repositorio baseline local. |
| `leer_entrega_agente_2` | Valida el repo del proyecto y lee insumos aprobados desde el commit indicado. |
| `publicar_arquitectura_local` | Publica una revisión aprobada sin commit, push ni PR. |
| `iniciar_arquitectura` | Valida y persiste la primera propuesta de un expediente. |
| `consultar_arquitectura` | Devuelve el estado, revisión, paquete y decisión pendiente. |
| `obtener_handoff_finops` | Devuelve a Codex únicamente el handoff vigente, aprobado y listo. |
| `preparar_publicacion_github` | Entrega a Codex el plan inmutable de rama, commit, archivos y PR. |
| `registrar_pull_request_github` | Valida y conserva el recibo devuelto por GitHub MCP. |
| `registrar_aprobacion_pr_github` | Valida aprobación, `head_sha` y merge commit exactos. |
| `preparar_issue_finops` | Construye el issue FinOps desde el handoff aprobado. |
| `registrar_issue_finops_github` | Conserva el recibo del issue creado por GitHub MCP. |
| `corregir_arquitectura` | Crea una revisión completa después de cambios solicitados. |
| `revisar_arquitectura` | Registra `approve` o `revise` para la revisión y SHA-256 exactos. |
| `solicitar_correccion_finops` | Reabre una entrega mediante una solicitud FinOps versionada. |
| `aplicar_correccion_finops` | Crea una revisión nueva vinculada a la solicitud recibida. |
| `consultar_historial_arquitectura` | Devuelve revisiones, correcciones, aprobaciones y handoffs. |

La configuración puede comprobarse con:

```powershell
codex mcp get aws_architecture
```

## Documentos generados

El paquete aprobado puede producir los siguientes documentos:

| Documento | Contenido |
| --- | --- |
| `requirements.md` | Requisitos y procedencia declarada. |
| `architecture.md` | Servicios y recursos AWS propuestos. |
| `architecture.mmd` | Diagrama Mermaid como código. |
| `adrs.md` | Decisiones, alternativas y trade-offs. |
| `security.md` | Controles de seguridad y rutas de políticas. |
| `architecture-package.json` | Contrato completo y estructurado. |
| `pricing-inputs.json` | Consumos y supuestos para que FinOps consulte precios posteriormente. |
| `handoff-finops.json` | Revisión aprobada entregada a la etapa 4. |

`cost_assumptions` se conserva por compatibilidad con paquetes de Arquitectura
1.0. El contrato económico 1.1 usa modelos discriminados para S3, DynamoDB,
API Gateway, Lambda, KMS y CloudWatch Logs. Arquitectura no incluye precios
unitarios, subtotales ni costos: FinOps debe obtener precios y hacer los cálculos.

Un contrato económico 1.0 todavía puede leerse para recuperar expedientes
guardados, pero queda bloqueado con `economic_contract_upgrade_required`. La
migración es explícita: se debe seleccionar `service_type`, convertir cada
dimensión al modelo específico y aportar los atributos obligatorios. El sistema
no deduce clases de almacenamiento, tamaños, consistencia ni operaciones porque
hacerlo inventaría supuestos.

Si falta el presupuesto, una cantidad o su procedencia, el dato se representa
como `unknown`/`null` con una explicación. El diseño puede aprobarse, pero queda
`blocked_for_finops_inputs` y no avanza la etapa principal a FinOps.

La demostración escribe estos archivos en `project/backend/data/architecture-demo/`.
Esta carpeta contiene resultados generados, no código fuente del agente.

## Archivos utilizados por el agente 3

### Núcleo de Arquitectura

| Ruta | Función |
| --- | --- |
| `project/backend/app/architecture/models.py` | Modelos Pydantic del contrato de entrada, recursos, módulos, ADRs, seguridad y costos. |
| `project/backend/app/architecture/economics.py` | Contrato económico, unidades, procedencia, consumos y reglas de bloqueo. |
| `project/backend/app/architecture/corrections.py` | Contrato versionado de correcciones solicitadas por FinOps. |
| `project/backend/app/architecture/project_repository.py` | Contrato agente 2 → 3, lectura Git fijada a commit y publicación local versionada. |
| `project/backend/app/architecture/state.py` | Estado serializable conservado por LangGraph. |
| `project/backend/app/architecture/catalog.py` | Lectura y validación del repositorio de módulos baseline. |
| `project/backend/app/architecture/nodes.py` | Nodos de validación, revisión humana y handoff. |
| `project/backend/app/architecture/graph.py` | Topología del grafo LangGraph especializado. |
| `project/backend/app/architecture/service.py` | Versiones, aprobación exacta, persistencia y coordinación con el workflow general. |
| `project/backend/app/architecture/mcp_server.py` | Servidor MCP dedicado que Codex inicia por STDIO. |
| `project/backend/app/architecture/demo.py` | Demostración local visible del flujo del agente. |
| `project/backend/app/architecture/__init__.py` | Declaración del paquete Python. |

### Integración con el backend existente

| Ruta | Uso por el agente 3 |
| --- | --- |
| `project/backend/app/bootstrap.py` | Compone catálogo, grafo, servicio y persistencia dentro del runtime general. |
| `project/backend/app/mcp_server.py` | También expone herramientas de Arquitectura desde el MCP general existente. |
| `project/backend/app/integrations/langgraph.py` | Adapta el contrato interno a snapshots, actualización y reanudación de LangGraph. |
| `project/backend/app/workflow/graph.py` | Grafo principal de las seis etapas. |
| `project/backend/app/workflow/state.py` | Identifica Arquitectura como etapa 3 y FinOps como etapa 4. |
| `project/backend/app/workflow/transitions.py` | Reglas deterministas de avance, revisión y devolución FinOps → Arquitectura. |
| `project/backend/app/workflow/service.py` | Registra eventos y sincroniza el proceso general. |
| `project/backend/app/workflow/runtime.py` | Mantiene los servicios compartidos por las entradas del backend. |
| `project/backend/app/persistence/workflow.py` | Artefactos, fases, eventos, sesiones, métricas y handoffs. |
| `project/backend/app/persistence/checkpoints.py` | Checkpoints SQLite o PostgreSQL de LangGraph. |
| `project/backend/app/persistence/locking.py` | Exclusión local compatible con Windows y Unix. |
| `project/backend/requirements.txt` | Dependencias, incluida PyYAML para leer manifiestos baseline. |

### Entradas, ejemplos e instrucciones

| Ruta | Función |
| --- | --- |
| `AGENTS.md` | Reglas para que Codex actúe como agente 3 y no invente evidencia o aprobaciones. |
| `project/backend/examples/architecture-1.json` | Propuesta de ejemplo utilizada por la demostración. |
| `project/backend/examples/architecture-serverless.json` | Ejemplo completo para API Gateway y DynamoDB. |
| `issues.md` | Especificación funcional general de los seis agentes. |
| `project/backend/README.md` | Documentación operativa del backend y herramientas MCP. |

### Repositorio de módulos baseline

El catálogo se obtiene del repositorio hermano
`aws-cloud-consultant-baseline-modules`. Para cada módulo se consultan:

- `aws/<modulo>/module.yaml`: versión candidata, estado y perfiles.
- `aws/<modulo>/audit-record.yaml`: revisión, aprobación y validación AWS.
- `aws/<modulo>/variables.tf`: entradas requeridas y validaciones.
- `aws/<modulo>/outputs.tf`: salidas disponibles para consumidores.
- `aws/<modulo>/README.md`: uso y limitaciones.

Actualmente se detectan S3, DynamoDB y API Gateway. Los tres se encuentran en
estado `draft` y con aprobación de producción pendiente.

### Pruebas

| Ruta | Cobertura |
| --- | --- |
| `project/backend/tests/architecture_agent/test_architecture.py` | Contrato, catálogo, revisiones, persistencia, MCP y transición a FinOps. |
| `project/backend/tests/architecture_agent/test_demo.py` | Exportación visible y confirmación de que no se genera Terraform. |
| `project/backend/tests/architecture_agent/test_dedicated_mcp.py` | Frontera del MCP dedicado y conjunto exacto de herramientas. |
| `project/backend/tests/workflow/test_process_workflow.py` | Reglas generales de avance, aprobación y retrabajo entre etapas. |

## Cómo ejecutar y comprobar

Desde `project/backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\architecture_agent
```

Para comprobar también el workflow principal:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\architecture_agent tests\workflow\test_process_workflow.py
```

Comprobación de calidad:

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests\architecture_agent
```

Demostración visible:

```powershell
.\.venv\Scripts\python.exe -m app.architecture.demo
Invoke-Item .\data\architecture-demo
```

La demo carga una propuesta conocida, ejecuta el grafo, simula una aprobación y
exporta documentos. Sirve como demostración técnica, pero no sustituye una prueba
interactiva de Codex construyendo el diseño desde requisitos reales.

## Trabajo pendiente

### Estado del Bloque C — implementación local lista; recarga MCP pendiente

El contrato de entrada `ArchitectureProjectHandoff` v1.1 fija repositorio,
commit, issue, revisión, un manifiesto de cuatro documentos obligatorios y la
evidencia de aprobación. La lectura usa blobs del commit, la publicación es
inmutable e idempotente y el handoff hacia FinOps solo puede recuperarse para la
revisión vigente aprobada. Las pruebas locales cubren casos positivos y negativos.

El 8 de noviembre de 2026 se invocó realmente por MCP
`consultar_catalogo_baselines`, que devolvió `api-gateway`, `dynamodb` y `s3`.
Esta sesión de Codex conservó el inventario antiguo de cinco herramientas y no
expuso `leer_entrega_agente_2`, `publicar_arquitectura_local` ni
`obtener_handoff_finops`. El recorrido completo no se considera una ejecución
MCP real hasta recargar el servidor en una conversación nueva y llamar esas
herramientas. Las pruebas Python no sustituyen esa evidencia.

La aprobación del repositorio local de prueba usa `evidence_type: test`; no es
una aprobación humana del proyecto. En la demostración real, Codex debe detenerse
en la interrupción y esperar una decisión explícita sobre revisión y SHA-256.

Para el Bloque D queda registrada la decisión de usar
`awslabs/diagram-as-code`, con `ArchitecturePackage` como fuente de verdad,
relaciones tipadas y generación determinista. No se implementa en el Bloque C.

### Estado del Bloque D — implementación local

`ArchitecturePackage` 1.2 agrega una topología tipada. Cada nodo corresponde a
un recurso existente y usa un tipo AWS incluido en el catálogo local verificado;
las relaciones distinguen flujo funcional de dependencia de despliegue. Las
dependencias no pueden ser desconocidas, autorreferentes ni cíclicas.

Mermaid y `architecture.aws-dac.yaml` se derivan de esa topología; el texto libre
ya no es la fuente de verdad en 1.2. Los contratos 1.0 y 1.1 conservan temporalmente
su campo Mermaid para compatibilidad. El YAML fija la definición oficial y el CLI
`awslabs/diagram-as-code` en `v0.24`.

La publicación 1.2 genera e incluye:

- `architecture.mmd`.
- `architecture.aws-dac.yaml`.
- `architecture.png`, renderizado por `awsdac v0.24`.
- `resources.yaml`.
- `module-selection.yaml`.
- Políticas IAM JSON declaradas explícitamente bajo `policies/`.
- `manifest.json` con SHA-256 de archivos de texto, políticas y PNG.

El adaptador rechaza una versión diferente de `awsdac`. En Windows busca primero
el binario local verificado en `project/backend/tools/awsdac/v0.24/`; también se
puede definir `AWSDAC_EXECUTABLE`. Los binarios descargados no se versionan.

Un clon nuevo prepara la dependencia desde `project/backend/` con:

```powershell
.\scripts\install_awsdac.ps1
.\.venv\Scripts\python.exe -m pytest -q tests\architecture_agent
```

`tools/awsdac/dependencies.json` es la fuente versionada de plataforma, asset y
SHA-256. El instalador detecta sistema operativo y arquitectura, verifica el
archivo antes de extraerlo y confirma `awsdac v0.24`. En Linux o macOS se ejecuta
con `pwsh ./scripts/install_awsdac.ps1`.

La renderización real de control produjo un PNG de 18 576 bytes con SHA-256
`b90bced6be739345e030e1b19b62d48c3e28dc3b5d59b1e27e46b0e34a83f55b`.
La evidencia local está en `project/backend/data/block-d-diagram/`, carpeta
ignorada por Git.

### 1. Demostración real de Codex y MCP

El servidor está registrado y las herramientas se prueban de forma aislada, pero
se debe conservar evidencia de una conversación completa donde Codex:

1. Lea requisitos reales.
2. Consulte `consultar_catalogo_baselines`.
3. Construya el paquete sin usar el JSON de demostración.
4. Registre la propuesta mediante `iniciar_arquitectura`.
5. Presente preguntas, módulos `draft`, revisión y hash.
6. Procese una aprobación o solicitud de cambios explícita.

### 2. Extensiones futuras del contrato económico

El contrato base ya incluye servicio, región, dimensiones, unidades, periodo,
atributos de precio, presupuesto y procedencia. Antes del agente 4 todavía deben
acordarse los escenarios mínimo/esperado/máximo y ampliar el catálogo tipado de
métricas cuando se incorporen nuevos servicios AWS. Las fuentes de precios y los
cálculos siguen deliberadamente fuera del agente 3.

### Correcciones solicitadas por FinOps — implementado localmente

El workflow general y el especializado ya permiten regresar de etapa 4 a etapa
3. La solicitud identifica la revisión, recursos, dimensiones, evaluación y
restricciones. Cada paquete modificado obtiene revisión y hash nuevos, vuelve a
aprobación humana y produce un handoff diferente. SQLite conserva las revisiones
anteriores sin sobrescribirlas; PostgreSQL continúa pendiente del Bloque F.

El contrato `FinOpsCorrectionRequest` 1.0 exige una referencia trazable a la
evaluación (`finops://`, `artifact://` o `https://`), alcance afectado, cambios,
restricciones, origen y fecha con zona horaria. Una corrección idéntica a la
arquitectura entregada se rechaza. Repetir la misma solicitud o la misma
aplicación devuelve un resultado idempotente; reutilizar el identificador con
otro contenido produce conflicto.

Las herramientas `solicitar_correccion_finops` y
`aplicar_correccion_finops` están registradas en el servidor dedicado. La
evidencia MCP real requiere que la sesión de Codex recargue el inventario del
servidor; las pruebas locales no se presentan como invocaciones MCP.

### 4. Políticas como código reales

Actualmente el contrato registra controles y rutas propuestas. Falta definir el
formato acordado —por ejemplo OPA/Rego, AWS Config o reglas de validación—, generar
los archivos y validarlos automáticamente. No se debe presentar una ruta como
política implementada si el archivo no existe.

### Publicación local en el repositorio del proyecto — implementado

La entrega del agente 2 identifica repositorio, commit, issue, revisión aprobada
y SHA-256 de cada insumo. El agente 3 lee los blobs del commit —no archivos
locales potencialmente modificados— y publica cada revisión aprobada en
`docs/03-architecture/versions/vNNN/` con un manifiesto de hashes. La operación
es idempotente y no hace commit, push ni PR; esas operaciones pertenecen a la
integración GitHub pendiente.

### Contrato real Agente 2 → Arquitectura 1.2 — implementado localmente

`ArchitectureProjectHandoff` acepta las versiones 1.1 y 1.2. La versión 1.1
conserva sin cambios el contrato de cuatro documentos usado por los primeros
fixtures. La versión 1.2 representa la entrega real del agente 2:

- Una o más evidencias bajo `docs/01-discovery/`.
- Un único `board_record` JSON bajo `docs/02-board/`.
- Evidencias Markdown, HTML, JSON, YAML o PDF con `media_type` explícito.
- Commit Git, SHA-256 de cada blob, issue, revisión y repositorio de origen.
- Presupuesto aceptado, partidas cuya suma coincide con el total y condiciones.
- `request_sha256` del paquete sometido a votación y `digest` del acta.
- Regla de unanimidad, miembros, votos y condición simulada.

Los hashes se calculan sobre los blobs del commit, no sobre el working tree; así
la conversión LF/CRLF de Windows no altera la evidencia. Los PDF se verifican por
SHA-256, pero su contenido binario no se incluye en la respuesta MCP. Markdown,
HTML y JSON sí se entregan como texto UTF-8 para construir la arquitectura.

`signature_verified: true` dentro del acta se conserva como
`declared_by_source`. El agente 3 no afirma haber realizado una verificación
criptográfica independiente porque no recibe las firmas ni los secretos usados
por el agente 2. Del mismo modo, `is_simulated: true` produce evidencia de tipo
`test` y nunca sustituye la aprobación humana posterior de Arquitectura.

La prueba de integración local utiliza como referencia
`aws-cloud-consulting-project-nike-01-lindora-run`, pero el contrato no contiene
nombres de Nike ni nombres fijos de actas o evidencias.

### 6. Integración con GitHub MCP — frontera local implementada

Codex, no el agente 3, ejecuta GitHub MCP. El agente 3 produce un plan inmutable
con repositorio, commit base, rama determinista, archivos con SHA-256, mensaje de
commit y contenido del PR. Después valida y persiste los recibos que Codex obtiene
de GitHub MCP.

En modo GitHub obligatorio, el handoff FinOps no se libera hasta registrar:

- El commit con exactamente todos los archivos y hashes planificados.
- El PR abierto sobre `main` y el commit base esperado.
- La aprobación del `head_sha` exacto.
- El merge commit resultante.

Solo entonces se prepara el issue FinOps con PR, merge commit, región, recursos,
módulos, revisión, hash y handoff tipado. Los reintentos idénticos son idempotentes
y un recibo diferente para la misma revisión se rechaza.

Continúa pendiente la demostración remota mediante un GitHub MCP conectado y
autorizado: crear realmente rama, commit, PR e issue, consultar la revisión y
registrar sus recibos. También falta el flujo separado para solicitar cambios en
el repositorio baseline cuando no exista un módulo. Los webhooks y un issue
cerrado siguen siendo evidencia; nunca aprueban automáticamente una etapa.

### 7. Modificaciones del catálogo baseline

Cuando no exista un módulo requerido, el agente debe coordinar un cambio separado
en `aws-cloud-consultant-baseline-modules`, ejecutar sus pruebas, evaluar impacto
en consumidores y abrir un PR que requiera aprobación del arquitecto.

### 8. Métricas completas

Se registra el límite de la etapa, pero falta instrumentar de forma completa:

- Trabajo activo de Codex.
- Tiempo de revisión humana.
- Espera de aprobación.
- Retrabajo solicitado por el arquitecto o FinOps.
- Aceptación del handoff por FinOps.

Lead Time y Process Time no deben inferirse a partir de la apertura o cierre de
issues; deben calcularse con eventos e intervalos persistidos.

### 9. PostgreSQL para el recorrido integrado

El MCP dedicado utiliza SQLite para la demostración local. El issue establece
PostgreSQL para la orquestación. Se debe ejecutar una prueba integrada con
PostgreSQL para checkpoints, artefactos, métricas y handoffs, manteniendo SQLite
como alternativa local cuando corresponda.

### 10. Validación de commits y procedencia

El contrato comprueba el formato de un SHA de 40 caracteres, pero todavía debe
verificar que el commit seleccionado exista en el repositorio baseline y que el
contenido consultado corresponda a ese commit. La validación debe funcionar sin
confundir el estado local con una aprobación remota.

### 11. Regresión completa del repositorio

Las pruebas propias del agente pasan. La regresión completa tiene problemas
preexistentes relacionados con referencias de preparación ausentes, entre ellas
`references/provenance.json`. Deben resolverse o documentarse antes de presentar
la integración completa como estable.

## Plan incremental

### Incremento A — Razonamiento real de Codex

- Ejecutar un caso nuevo sin utilizar `architecture-1.json`.
- Confirmar las cinco llamadas MCP y guardar evidencia anonimizada.
- Añadir una prueba de contrato basada en el resultado producido.
- Verificar que Codex no apruebe automáticamente su propia propuesta.

**Criterio de salida:** propuesta creada desde requisitos reales y decisión humana
registrada con revisión y hash exactos.

### Incremento B — Handoff FinOps v1

- Ampliar los modelos con `pricing_inputs` estructurados.
- Definir moneda, periodo, escenarios y exclusiones.
- Validar que cada entrada de precio se relacione con un recurso.
- Acordar el contrato con el agente 4 y con el consumidor de los casos 21/22.

**Criterio de salida:** FinOps puede calcular sin interpretar texto libre ni
preguntar qué cantidad corresponde a cada servicio.

### Incremento C — Retrabajo FinOps → Arquitectura

- Reabrir el grafo especializado al regresar a etapa 3.
- Crear una nueva iteración y revisión.
- Mantener trazabilidad entre issue FinOps, diseño anterior y diseño corregido.
- Evitar handoffs duplicados.

**Criterio de salida:** una devolución de FinOps produce una revisión arquitectónica
nueva y un segundo handoff verificable.

### Incremento D — Artefactos completos

- Definir la estructura final de `docs/03-architecture/`.
- Generar políticas como código reales y validarlas.
- Generar manifests de recursos, módulos y entradas de precios.
- Verificar coherencia entre documentos y paquete JSON.

**Criterio de salida:** todos los artefactos se regeneran desde una única revisión
y comparten recursos, región, módulos y supuestos.

### Incremento E — GitHub MCP

- Conectar lectura de issues y publicación de archivos.
- Implementar rama, commit y PR con autorización explícita.
- Registrar aprobación real del arquitecto.
- Crear el issue de FinOps y enlazar antecedentes.

**Criterio de salida:** recorrido issue de Arquitectura → PR aprobado → issue FinOps
con referencias verificables.

### Incremento F — Métricas y PostgreSQL

- Instrumentar intervalos humanos y del agente.
- Registrar aceptación del handoff.
- Probar recuperación, concurrencia e idempotencia con PostgreSQL.
- Incorporar los checks a CI.

**Criterio de salida:** Lead Time, Process Time, espera y retrabajo consultables con
procedencia explícita y persistencia después de reiniciar.

## Criterio para completar el issue #19

El issue no debe marcarse como completado hasta demostrar, como mínimo:

- Diseño creado por Codex a partir de insumos reales.
- Catálogo y commits baseline verificables.
- Diagrama, ADRs, seguridad, políticas y entradas FinOps coherentes.
- Revisión y aprobación humana exactas.
- Publicación en `docs/03-architecture/` mediante PR aprobado.
- Handoff aceptable por FinOps.
- Corrección FinOps → Arquitectura funcional.
- Métricas y handoffs persistidos.
- Pruebas locales y CI sin afirmar validaciones AWS no ejecutadas.
- Ausencia de `terraform apply` y de operaciones destructivas en AWS.
