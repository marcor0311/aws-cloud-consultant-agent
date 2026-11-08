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
```

Codex proporciona el razonamiento del agente. El servidor MCP no inventa el
diseño: valida, versiona, persiste y protege la aprobación de la propuesta
construida por Codex a partir de los requisitos disponibles.

## Herramientas MCP

El servidor MCP registrado en Codex se llama `aws_architecture` y utiliza
transporte STDIO. Expone únicamente las herramientas de Arquitectura:

| Herramienta | Responsabilidad |
| --- | --- |
| `consultar_catalogo_baselines` | Lee módulos, perfiles, versiones y estados reales del repositorio baseline local. |
| `iniciar_arquitectura` | Valida y persiste la primera propuesta de un expediente. |
| `consultar_arquitectura` | Devuelve el estado, revisión, paquete y decisión pendiente. |
| `corregir_arquitectura` | Crea una revisión completa después de cambios solicitados. |
| `revisar_arquitectura` | Registra `approve` o `revise` para la revisión y SHA-256 exactos. |

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

### 3. Correcciones solicitadas por FinOps

El workflow general puede regresar de la etapa 4 a la etapa 3, pero el grafo
especializado debe permitir reabrir un diseño que ya quedó `ready_for_finops`.
Debe crear una nueva iteración, conservar referencias a revisiones anteriores y
generar otro handoff sin sobrescribir evidencia.

### 4. Políticas como código reales

Actualmente el contrato registra controles y rutas propuestas. Falta definir el
formato acordado —por ejemplo OPA/Rego, AWS Config o reglas de validación—, generar
los archivos y validarlos automáticamente. No se debe presentar una ruta como
política implementada si el archivo no existe.

### 5. Publicación en el repositorio del proyecto

Los documentos deben publicarse en `docs/03-architecture/` del repositorio creado
desde `aws-cloud-consulting-project-template`, en vez de permanecer únicamente en
`data/architecture-demo/` o en la base local.

### 6. Integración con GitHub MCP

Falta implementar el recorrido documentado en el issue:

- Leer el issue asignado y los insumos anteriores.
- Crear una rama de trabajo autorizada.
- Publicar documentos de Arquitectura.
- Crear un PR y solicitar revisión del arquitecto.
- Comprobar la aprobación real del PR.
- Cerrar el issue de Arquitectura.
- Crear y asignar el issue de FinOps con commit, módulos, región, recursos,
  presupuesto, supuestos y referencias anteriores.

Los webhooks y un issue cerrado deben utilizarse como evidencia, no como aprobación
humana implícita.

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
