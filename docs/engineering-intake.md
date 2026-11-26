# Ingeniería: entrada, evidencias y métricas · #21

Este incremento implementa las prioridades 1–3: recibir los insumos aprobados,
consolidar evidencias existentes y registrar sus intervalos técnicos. No ejecuta
Terraform ni AWS Emulator, no publica PRs y no aprueba infraestructura. El recorrido
S3 de demostración y `DemoRequest` conservan su contrato anterior.

## Entrada versionada

`EngineeringIntake` está en `app/delivery/engineering_models.py`. La entrada puede
prepararse manualmente; los agentes #19/#20 no necesitan estar automatizados.
Las decisiones y la entrega previas sí deben estar registradas en el workflow.
Este contrato v1 debe acordarse con Arquitectura y FinOps antes de usar un piloto real.

| Campo | Contenido |
| --- | --- |
| `intake_id`, `case_id` | UUID inmutable de recepción y expediente existente. |
| `repository` | `owner/repo` del proyecto de consultoría. |
| `incoming_handoff_id` | Entrega existente de etapa 4 a etapa 5, asignada al operador. |
| `architecture` | Commit completo, revisión, archivos y referencia a su decisión aplicada. |
| `finops` | Commit de costos, revisión, archivos y referencia a su decisión aplicada. |
| `finops_architecture_commit`, `finops_architecture_sha256` | Commit y manifiesto exactos del diseño que FinOps evaluó. |
| `modules` | Repositorio, ruta, commit completo y referencias de aprobación de cada baseline. |
| `region` | Región del diseño; no se deduce de archivos ni de credenciales. |
| `budget`, `estimate`, `currency`, `period` | Importes comparables del presupuesto y la estimación, en una moneda y periodo explícitos (`month` o `year`). |
| `calculator_url` | Enlace HTTPS de AWS Pricing Calculator. Se conserva como referencia, sin abrirlo ni recalcular precios. |

Cada archivo declara `role`, `path` relativo al directorio de insumos, `sha256`
y `reference`. Las referencias de los documentos deben apuntar al repositorio y
commit exactos, con `https://github.com/<owner/repo>/blob/<commit>/...`.

Arquitectura entrega exactamente `requirements`, `design` y `policies`.
FinOps entrega `calculator_export` (CSV/PDF) y `cost_workbook` (XLSX).
El receptor comprueba bytes y hashes; la validación del contenido financiero
pertenece a FinOps. No convierte una referencia a Excel en una estimación verificada.

La aprobación de cada paquete indica `event_id`, `actor` y `reference`. Se contrasta
con una transición `stage.approved` aplicada en SQL para la misma etapa, revisión,
hash y actor; su evidencia debe incluir esa referencia. También se verifica la
secuencia de iteraciones y que la entrega recibida sea la de FinOps correspondiente.
No basta con añadir un booleano `approved` a un JSON.

Los hashes aprobados incluyen los metadatos: el de Arquitectura fija documentos,
repositorio, commit, revisión, módulos y región; el de FinOps fija documentos,
dependencia del diseño, importes, moneda, periodo y calculadora. El algoritmo
`approval_digest(3/4)` es público en el modelo. El hash de la entrada completa
`input_sha256` incluye además sus referencias de aprobación y recepción.

La comprobación acredita correspondencia con decisiones del workflow local.
No autentica una revisión externa de GitHub: las aprobaciones de baselines
permanecen como referencias declaradas pendientes de verificación externa.
El runtime sigue siendo de un único operador, sin autorización empresarial por rol.

## Operación local

Desde `project/backend`, con las dependencias del backend instaladas:

```powershell
$env:ENGINEERING_OPERATOR = 'identificador-del-responsable'
# Configurar WORKFLOW_DATABASE_URL con el PostgreSQL existente del proceso.
python -m app.cli.engineering manifest --input entrada-ingenieria.json
python -m app.cli.engineering intake --input entrada-ingenieria.json --artifact-root ../generated/engineering-inputs
python -m app.cli.engineering evidence --input evidencia-ingenieria.json --artifact-root ../generated/engineering-inputs
python -m app.cli.engineering status --intake-id UUID-DE-LA-ENTRADA
```

El operador debe coincidir con el responsable del expediente y destinatario del
handoff. La primera recepción correcta acepta esa entrega y abre el registro
de tiempos de etapa 5 si aún no existe. No adelanta el grafo a la siguiente etapa.
Recepción, archivos y evento se confirman en una transacción SQL.

Antes de registrar las aprobaciones, `manifest` permite calcular sus hashes sin
acceder a SQL. Para preparar una entrada nueva, usar temporalmente 64 ceros en
`finops_architecture_sha256`, obtener `architecture_sha256`, copiarlo a ese campo
y ejecutar otra vez `manifest` para obtener el hash definitivo de FinOps. Las
decisiones previas deben referenciar los hashes definitivos. Registrar una entrada
con el valor provisional es rechazado.

El esquema completo se obtiene sin red desde Python:

```powershell
python -c "import json; from app.delivery.engineering_models import EngineeringIntake; print(json.dumps(EngineeringIntake.model_json_schema(), indent=2))"
```

Usar el mismo comando con `EngineeringEvidence` para el contrato de resultados.
El ingreso de un paquete incompleto, con revisión incompatible, presupuesto excedido,
archivo cambiado o aprobación ausente no acepta el handoff ni crea una recepción parcial.

## Evidencias existentes

`EngineeringEvidence` registra una corrida por `run_id` UUID y `intake_id`:

- `input_sha256` vincula los resultados a la entrada exacta, incluidos los costos.
- `implementation_commit` y `implementation_tree_sha256` vinculan el código probado
  con sus archivos. Este último se calcula con `package_digest` sobre los archivos
  de rol `implementation`, ordenados por rol y ruta. El commit externo es declarado;
  los bytes locales y sus hashes sí se comprueban.
- `plan_sha256` identifica el plan cuando `terraform plan` pasó. El plan y el estado
  no se adjuntan. Los módulos deben coincidir exactamente con los de entrada.
- `versions` incluye Terraform, proveedor AWS, AWS Emulator y Trivy.
- `resources`, `run_reference` y `actor` identifican alcance, corrida y ejecutor
  declarados. El alcance admitido es `local_emulator`.
- `checks` enumera las once comprobaciones del runner existente, con `passed`,
  `failed` o `not_run`; omitir una no equivale a éxito. Una comprobación ejecutada
  requiere inicio/fin; una no ejecutada no tiene intervalo. El fallo indica origen
  o `undetermined`; no se deduce una limitación del emulador por un error de API.
- Los archivos usan roles `implementation`, `log`, `security_report` y
  `policy_report`. Informar todas las comprobaciones exitosas exige también los
  respaldos de logs, seguridad y políticas.

El importador verifica la raíz permitida, formatos de respaldo, hashes, límites
de tamaño y coincidencia con la entrada. Excluye rutas fuera de la raíz, archivos
de credenciales, planes/estado identificables y planes/estado JSON estándar.
Los exports deben prepararse sin secretos. Guarda los bytes originales en SQL,
sin depender de que los archivos locales permanezcan sin cambios.

`execution_verification` identifica estos resultados como registrados por el
operador, con integridad de archivos comprobada y ejecución no autenticada.
El importador no verifica una ejecución remota de CI ni transforma resultados
declarados en pruebas ejecutadas por el backend. `evidence_status` informa
`not_received`, `passed`, `failed` o `incomplete`; revisión e integración siguen pendientes.

Los JSON anteriores de `evidence.json`/`execution.json` de la demostración no son
entradas reales ni se convierten automáticamente a este contrato. Sus fuentes
simuladas siguen identificadas como tales. La ejecución de nuevas simulaciones
queda fuera de estos comandos.

## MCP de ingeniería

Iniciar el servidor privado STDIO con `python -m app.delivery.engineering_mcp`.
Configurar `WORKFLOW_DATABASE_URL`, `ENGINEERING_OPERATOR` y, opcionalmente,
`ENGINEERING_ARTIFACTS_DIR` (por defecto `project/generated/engineering-inputs`).

| Herramienta | Entrada |
| --- | --- |
| `registrar_entrada_ingenieria` | `entrada: EngineeringIntake` |
| `registrar_evidencias_ingenieria` | `evidencia: EngineeringEvidence` |
| `consultar_ingenieria` | `intake_id` |
| `consultar_catalogo_compatibilidad` | `intake_id` |
| `registrar_entrega_tecnica` | `entrega: EngineeringRelease` |

El recurso `engineering://artifact/<intake_id>/<sha256>` descarga los bytes
registrados del insumo o evidencia. Aplica el mismo control por expediente y
operador que las consultas. No se publica un endpoint HTTP nuevo.

## Métricas, reintentos y límites

La fase conserva su recepción registrada como inicio de LT y queda en curso:
el fin de una corrida no significa que el arquitecto haya aprobado la entrega.
Cada comprobación ejecutada añade un intervalo de agente a las sesiones existentes,
con referencia a la evidencia. Los intervalos deben estar entre la recepción
de entrada y el momento de importación; no se inventan fechas históricas.

`case_metrics` une los intervalos por actor para calcular esfuerzo y une todos
para duración activa. No añade otro intervalo padre de la corrida. El trabajo
humano registrado comparte esa fase y se mantiene separado del esfuerzo agente.
El informe por expediente #22 consume estas mismas mediciones al capturar otra
instantánea. Los PDF ya aprobados conservan sus métricas anteriores.

`kind=rework` mide retrabajo explícito. Si otros intervalos no están clasificados,
el total de retrabajo permanece desconocido y `recorded_rework_effort_seconds`
muestra únicamente la parte acreditada. Las brechas de actividad no se etiquetan
como espera; la espera de recepción del handoff permanece separada.

Repetir el mismo `intake_id` o `run_id` reutiliza el registro sin duplicar archivos,
aceptaciones ni intervalos. Reutilizarlo con otro contenido produce conflicto.
Los cambios de revisión requieren otro identificador. Una nueva iteración de
ingeniería invalida la recepción anterior para añadir corridas; se conserva su
historia. La nueva recepción puede usar los mismos insumos previos si sus
aprobaciones siguen vigentes. Si FinOps/Arquitectura cambian, exige sus nuevas decisiones.

La recepción y evidencias se guardan en `workflow_records`, los eventos en
`workflow_events` y las mediciones en `workflow_work_sessions`. No se crean tablas
ni migraciones nuevas. Las exclusiones existentes coordinan recepción/proceso.

El informe #22 ya puede consumir esta recepción con `intake_id`, conservar sus
evidencias y mostrar las comprobaciones y métricas en un PDF parcial. Ver
[selección y descarga desde el informe](revision-informe-ejecutivo.md).
Recibir evidencias o aprobar el informe parcial no aprueba infraestructura ni
completa #21. El registro de una entrega definitiva se describe a continuación.

## Catálogo y entrega definitiva

`python -m app.cli.engineering catalog --intake-id <uuid>` devuelve el catálogo
de esa recepción: revisión, SHA-256 e historial de combinaciones de módulos,
recursos y herramientas. Incluye corridas exitosas, fallidas e incompletas y los
límites del alcance declarado. Una combinación no observada sigue sin verificar.
La revisión corresponde al número de corridas y su hash identifica el contenido;
la entrega definitiva y cada informe conservan su propia copia del catálogo.
Los registros importados siguen siendo declaraciones del operador: el catálogo
no autentica ejecuciones externas ni acredita compatibilidad con AWS real.

`EngineeringRelease` registra una entrega técnica ya revisada e integrada:

- Recepción, hash de entrada, revisión y dos corridas distintas: local y CI.
  Ambas deben informar todas las comprobaciones correctas sobre el mismo commit
  y manifiesto de implementación. CI debe referenciar una ejecución Actions del
  repositorio del proyecto y la entrega debe incluir la última corrida registrada.
- PR del proyecto hacia `main`, commit probado/revisado, commit de merge y sus
  referencias. El arquitecto debe coincidir con el de la arquitectura aprobada.
- Confirmación de cada baseline exacto, referencia de protección de la rama y
  límites de compatibilidad revisados por el operador.
- ID de una decisión `stage.approved` de etapa 5 que coincida con el hash de la
  entrega, revisión, arquitecto, iteración y referencia de revisión.

Secuencia desde `project/backend`:

1. Preparar `entrega.json` con los campos de `EngineeringRelease`. Consultar el
   contrato con `python -c "from app.delivery.engineering_models import EngineeringRelease; import json; print(json.dumps(EngineeringRelease.model_json_schema(), indent=2))"`.
2. Calcular el hash con
   `python -m app.cli.engineering release-manifest --input entrega.json`.
   El hash excluye únicamente `approval_event_id`, evitando una dependencia circular.
3. Registrar `deliverable.ready` de etapa 5 con esa revisión/hash mediante el
   proceso existente. Tras la aprobación explícita del arquitecto y la integración
   del PR, registrar `stage.approved` con los mismos datos y la referencia de revisión.
4. Importar con `python -m app.cli.engineering release --input entrega.json`, o
   usar `registrar_entrega_tecnica` por MCP. Si falta la decisión exacta, se rechaza.
5. Consultar el estado: `approved_recorded` y `merged_recorded` indican una
   aprobación contrastada con el proceso y referencias externas confirmadas por
   el operador. No equivalen a una consulta autenticada a GitHub.

El registro definitivo es inmutable por recepción, conserva catálogo/hash y emite
`engineering.delivery_available` en SQL para la etapa 6. Completa la fase de
ingeniería e inicia la de informe. Los reintentos recuperan el mismo registro sin
duplicar el evento. El handoff de etapa 5 a 6 lo crea el proceso existente.

El registro manual anterior conserva su procedencia declarada. Las nuevas
operaciones `publish` e `integrate` automatizan el ciclo del PR y verifican
baselines, código, protección, CI y revisión mediante la API de GitHub. La entrega
encola un aviso para el worker de Slack. Ver [operación y requisitos](engineering-github.md).
Siguen pendientes el acuerdo/piloto con insumos reales de #19/#20 y la acreditación
del recorrido en los servicios reales. Los expedientes ficticios pueden documentar
el recorrido sin cerrar un proyecto real.
