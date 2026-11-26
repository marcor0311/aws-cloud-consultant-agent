# Revisión del informe ejecutivo · #22

El informe por expediente consolida registros existentes sin ejecutar ingeniería.
Puede generarse antes de completar #21: los faltantes se muestran y bloquean el
cierre real. Permite seleccionar una recepción de ingeniería por `intake_id`.
La entrega técnica de demostración es opcional y conserva su
identificación de arquitectura y FinOps simulados. El recorrido anterior de
ingeniería e informe continúa disponible exclusivamente como demostración.

En GitHub Actions, el workflow **Integración Terraform con AWS Emulator**
también ejecuta el recorrido del informe con el JSON de la misma corrida.
Los PDF y sus respaldos se conservan dentro del artefacto `issue21-<fixture>-<intento>`.

## Configurar

Desde `project/backend`, con las dependencias y PostgreSQL local configurados
según [Entrega 1](delivery-1.md):

```powershell
$env:DELIVERY_ENGAGEMENT_MANAGER = 'Nombre del operador de demostración'
python -m app.delivery init-db
python -m app.delivery.mcp
```

El último comando es para un cliente MCP con transporte STDIO. Configurar en
el cliente el ejecutable de Python del backend, los argumentos
`-m app.delivery.mcp` y las variables privadas `DELIVERY_DATABASE_URL` y
`DELIVERY_ENGAGEMENT_MANAGER`. La identidad registrada viene de esa configuración
del operador local.

| Herramienta | Acción |
| --- | --- |
| `generar_informe` | Consolidar un expediente con `report_id` y `case_id`; la entrada anterior `fixtures/delivery-1.json` conserva el ejemplo |
| `consultar_informe` | Consultar revisión vigente, tiempos, historial y URI de PDF |
| `registrar_decision_informe` | Guardar ajustes, revisión, aprobación o presentación |
| `consultar_conciliacion_mediciones` | Consultar faltantes y hash de las mediciones actuales |
| `conciliar_mediciones` | Aplicar correcciones explícitas con evidencia y auditoría |
| Recurso `delivery://pdf/{entrega_id}/{archivo_id}` | Leer el PDF descargable en un cliente MCP que admita recursos |

## Informe independiente del issue 21

Configurar también `WORKFLOW_DATABASE_URL` para la base PostgreSQL existente del
proceso. `DELIVERY_DATABASE_URL` conserva los informes; ambas pueden apuntar a la
misma base. Usar como `DELIVERY_ENGAGEMENT_MANAGER` el identificador exacto del
responsable registrado en `workflow_projects`, no un nombre nuevo para esta sesión.
El runtime es local y de un único operador; esto no añade autenticación empresarial.
El MCP no compone proveedores de Google, Slack o IA ni inicia workers.

### Transporte para el cliente del Engagement Manager

STDIO se conserva para clientes locales. Para ChatGPT web se recomienda el
transporte Streamable HTTP con el mismo guard Bearer privado del resto del backend:

```powershell
python -m app.delivery.mcp --transport streamable-http --host 127.0.0.1 --port 8770
```

Configurar `DELIVERY_MCP_BEARER_TOKEN` con al menos 32 caracteres en el directorio
privado o entorno del proceso. No guardar el token en documentación ni exponer
PostgreSQL. El servidor se mantiene en loopback; conectar mediante Secure MCP
Tunnel u otra conexión remota autorizada compatible con la cuenta. Seguir la
[guía oficial de conexión MCP en ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt-beta).

La prueba existente verifica inicialización JSON-RPC, listado de herramientas,
generación, ajustes, aprobación, bloqueo de cierre parcial y lectura de PDF/JSON
por HTTP real ASGI. Comprueba el rechazo sin Bearer en `/mcp` y `/mcp/`. No usa
un modelo ni una cuenta de ChatGPT: esa aceptación se realiza manualmente con
[este recorrido](validacion-cliente-informe.md).

### Conciliación de mediciones

Consultar `consultar_conciliacion_mediciones(expediente_id)` antes de corregir.
El resultado identifica fases ausentes/en curso, sesiones abiertas/sin clasificar,
sesiones fuera de límites y handoffs sin recepción; incluye `state_sha256`.

`conciliar_mediciones` recibe `MeasurementDecision`: `reconciliation_id`, `case_id`,
`expected_sha256`, `reference` y `detail`, más las correcciones explícitas:

- `phases`: `phase` (`stage-1` a `stage-6`), `accepted_at` y `completed_at` opcional.
- `sessions`: `session_id`, `ended_at` opcional y `kind` (`work`, `wait` o `rework`).
- `handoffs`: `handoff_id` y `accepted_at`.

Las fechas requieren zona horaria. Se verifican pertenencia, límites, sesiones
afectadas, fechas futuras y hash vigente. No se sobrescribe una clasificación
técnica distinta de su evidencia original. El cambio y su estado anterior se
guardan atómicamente en SQL; repetir la misma decisión no duplica auditoría.
Un expediente cerrado no admite correcciones nuevas.

Las esperas clasificadas se excluyen de PT y de duración activa. Se descuenta su
superposición con trabajo antes de calcular la espera. Los huecos sin registro
siguen sin clasificar; no se inventan sesiones ni trabajo histórico.

Cada informe congela también `measurement_review`. Una conciliación posterior
requiere otro informe y aprobación antes de presentar: el cierre rechaza un hash
de mediciones distinto, salvo la recuperación de su propia presentación aplicada.
Las fuentes anteriores conservan el estado previo. La conciliación de registros
no acredita datos que nunca se midieron; esos faltantes requieren evidencia real.

1. Consultar `listar_expedientes_informe` para seleccionar un `case_id` propio.
2. Llamar `generar_informe` con la nueva entrada:

   ```json
   {
     "entrada": {
       "report_id": "3322a904-81a4-4dd3-ab1d-8402da256ed9",
       "case_id": "expediente-existente"
     }
   }
   ```

3. Opcionalmente añadir `intake_id` con una recepción de ingeniería del mismo
   expediente. También se conserva `engineering_delivery_id` para la entrega
   anterior de demostración del mismo `project_id`. Elegir uno de los dos campos;
   ambos juntos se rechazan. Se verifican los archivos por hash y se mantiene
   su procedencia. Nunca se vuelve a ejecutar el nodo de ingeniería.
4. Consultar el informe y descargar `pdf_uri` y `sources_uri`. Este último recurso
   JSON contiene proyecto, presupuesto de dirección si existe, decisiones,
   manifiesto, entrega adjunta y mediciones que respaldan el documento. El PDF
   identifica el SHA-256 de ese respaldo.
5. Solicitar cambios con `request_changes`. Para `revise`, enviar además `sections`
   con una o más claves `results`, `risks`, `next_steps`. El contenido reemplaza la
   sección correspondiente, conserva las demás y genera una versión nueva.
6. `approve` aprueba exactamente esa versión como **informe parcial**. Se pueden
   pedir cambios sobre un informe aprobado, invalidando su aprobación vigente.
   El PDF anterior permanece disponible para auditoría.

Las fuentes se congelan al primer uso de `report_id`, incluso si falla el renderizado.
Repetir la petición recupera el mismo informe. Para incorporar información posterior
del expediente, usar otro `report_id`; no se reemplazan silenciosamente las fuentes
de una revisión aprobada. Los UUID del informe y de la entrega técnica son distintos.

La API local de revisión añade `POST /api/delivery/reports` con el contenido de
`entrada` como cuerpo. Las consultas y decisiones reutilizan las rutas existentes
usando el `delivery_id` devuelto (igual al `report_id` solicitado). Las nuevas rutas
solo se montan en la demostración de loopback, igual que las decisiones existentes.
La lectura, decisión y descarga de un informe por expediente exigen el operador
local con que se creó. No exponer esta API fuera de loopback.

### Adjuntar una recepción de ingeniería

Usar el `intake_id` devuelto por `registrar_entrada_ingenieria` del MCP de #21:

```json
{
  "entrada": {
    "report_id": "f8374064-478b-43b4-a222-b7c9e55ce161",
    "case_id": "expediente-existente",
    "intake_id": "f4c5253d-69a0-4716-942d-b783c3d5e10a"
  }
}
```

El operador local del informe debe ser el mismo responsable registrado de la
recepción. Se conserva el modelo actual de un único operador; esto no añade
transferencias de identidad entre cuentas de ingeniero y Engagement Manager.

La captura lee únicamente PostgreSQL: no necesita los archivos del directorio de
ingreso, no importa corridas nuevas y no ejecuta Terraform ni inferencia. Rechaza
recepciones de otro expediente y manifiestos o respaldos cuyos hashes no coincidan.
Las exclusiones de ingeniería/proceso protegen la lectura de recepción, corridas
y mediciones durante la captura.

El resultado contiene `engineering`, además del `handoff` anterior. Una recepción
no es una entrega técnica aprobada: el `handoff` permanece vacío cuando solo se
selecciona `intake_id`. `report.intake_id` identifica la recepción; el manifiesto de
fuentes identifica las corridas y hashes. `engineering.selected_run_id` señala la
última corrida importada al corte, usada en la tabla de comprobaciones, versiones
y recursos. Se conserva también el historial de corridas y archivos respaldados.

El PDF incorpora presupuesto y estimación de FinOps con moneda/periodo explícitos,
calculadora, referencia del Excel, módulos y commits, estados de comprobaciones,
pendientes e integridad de respaldos. Distingue resultados declarados por el
operador de una ejecución autenticada. Una recepción sin corridas, con fallos o
de una iteración anterior puede documentarse como borrador parcial; esos pendientes
no se convierten en aprobación técnica.

`sources_uri` permite descargar el JSON congelado. Cada archivo de
`engineering.files` incluye un `uri` servido por el mismo MCP del informe:
`delivery://engineering/<report_id>/<sha256>`. Solo permite descargar archivos
incluidos en esa instantánea y vuelve a comprobar sus bytes. Un informe anterior
no obtiene acceso automático a los archivos de corridas posteriores.

Para incluir una corrida nueva de la misma recepción, generar otro `report_id`.
La misma petición recupera sus fuentes y PDF originales, incluso si ahora hay más
resultados o cambió la vigencia del proceso. Las revisiones y aprobaciones de ese
informe usan la instantánea congelada. Los informes anteriores sin selección de
recepción conservan su identificación e idempotencia.

### Métricas y límites

- LT se obtiene de límites registrados de cada fase; las fases abiertas se marcan
  en curso y las ausentes muestran `null` / "Sin medición".
- PT suma esfuerzo registrado por actor, uniendo sus intervalos superpuestos.
  La duración activa une todos los intervalos, sin sumar dos veces fases de detalle.
- Se muestran esfuerzo humano/agente, sesiones abiertas, ciclos de cambios y
  espera entre creación y recepción de cada handoff, con recepción pendiente explícita.
- Los intervalos técnicos importados desde #21 aportan esfuerzo y retrabajo
  explícitamente clasificado. El PDF muestra ese retrabajo como parcial cuando
  otros intervalos de la fase siguen sin clasificar. La espera de fase sin registro
  continúa sin medición; el tiempo restante no se convierte en espera.
- El presupuesto de dirección no declara periodo. No se compara automáticamente
  con la estimación mensual simulada de FinOps. El gasto real sigue sin información.
- `metrics` es la instantánea del expediente al corte. `report_activity_metrics`
  muestra aparte la generación y las revisiones del PDF; no se inventa tiempo de
  lectura humana ni se infiere el LT global sumando fases.

`record_presentation` devuelve conflicto para estos informes parciales. Una entrega
definitiva posterior no modifica sus fuentes: generar otro `report_id` para
capturarla y someter ese documento a revisión.

### Presentación y cierre del expediente

Cuando la recepción tiene una `EngineeringRelease` vigente, con corridas exitosas
local/CI y aprobación exacta de etapa 5 registrada, el nuevo informe incorpora
esa entrega y el catálogo congelado. Si el expediente es real y no hay bloqueos
técnicos, el PDF se identifica como definitivo. Los datos ausentes de métricas
siguen mostrando "Sin medición"; definitivo no significa medición completa ni
autenticación remota de las referencias confirmadas por el operador.

Tras revisar y aprobar la versión/SHA-256 exactos, `record_presentation` requiere
además de `decision_id`, `version`, `sha256`, `action` y `detail`:

```json
{
  "presentation": {
    "presented_at": "2026-11-25T21:00:00Z",
    "audience": "Dirección del proyecto",
    "reference": "https://example.org/actas/presentacion"
  }
}
```

Es un ejemplo de estructura; registrar la fecha y el acta reales. La fecha debe
ser posterior a la aprobación del informe y no estar en el futuro. El servicio
verifica los PDFs y las fuentes, vuelve a comprobar la entrega vigente y exige
que el proceso siga en la misma iteración de etapa 6. No promueve un informe
parcial, ficticio, desactualizado o aprobado sobre otro hash.

La operación aplica `deliverable.ready` y `stage.approved` al grafo principal con
referencias a ambos PDFs y a la presentación; completa la fase 6 y deja el proceso
en `completed`. La entrega de informe queda `closed`. Los eventos y la decisión
conservan identificadores estables para recuperar una interrupción entre el
checkpoint y el guardado del informe: reintentar exactamente la misma decisión.
Las dos bases no comparten una transacción; durante esa recuperación el proceso
puede estar completado y el informe aún aprobado. Una decisión distinta no puede
reemplazar la presentación ya aplicada.

El mismo recorrido está disponible por MCP y por la API local de revisión cuando
se configura `WORKFLOW_DATABASE_URL`. El Engagement Manager no necesita operar
GitHub. Quedan por validar el cliente MCP elegido y el piloto con entregables,
mediciones, aprobaciones y presentación reales.

## Descarga desde el cliente MCP

Además de los recursos `delivery://`, el transporte HTTP permite
`preparar_descarga_informe(entrega_id)` cuando se configura
`DELIVERY_DOWNLOAD_BASE_URL` con el origen HTTPS existente del servidor. Devuelve
un enlace temporal al PDF vigente y otro a la instantánea JSON de fuentes, sus
hashes, tamaños y caducidad de cinco minutos. La descarga comprueba propiedad,
firma e integridad; no cambia el estado de aprobación o presentación.
El enlace actúa como permiso temporal sobre un archivo: mantenerlo dentro de la
conversación autorizada. No hace falta enviar el Bearer desde el navegador.
Ver [recorrido de aceptación y configuración](validacion-cliente-informe.md).

## Revisar y cerrar la demostración anterior

1. Consultar el borrador y tomar `report.version` y `report.artifact.sha256`.
2. Enviar una decisión con un `decision_id` UUID nuevo, la versión, su SHA-256,
   la acción `request_changes` y los cambios solicitados en `detail`.
3. Enviar `revise` sobre la misma revisión con la actualización ejecutiva en
   `detail`. El backend guarda una nueva versión y conserva el PDF anterior.
4. Confirmar `approve` sobre la revisión vigente. La copia PDF aprobada
   incluye el operador, la fecha, la decisión y el hash del PDF revisado.
5. Tras presentar el informe, registrar `record_presentation` con la referencia
   de la sesión o acta. Eso cambia la entrega local a `closed`.

La API de demostración en loopback permite el mismo recorrido en una interfaz
web. Ejecutar `python -m uvicorn app.demos.delivery:app --host 127.0.0.1 --port 8011`
y usar [OpenAPI local](http://127.0.0.1:8011/docs). Las rutas de revisión no se
montan en el backend HTTP principal.

| Operación | Ruta |
| --- | --- |
| Consultar informe | `GET /api/delivery/runs/{delivery_id}/report` |
| Registrar decisión | `POST /api/delivery/runs/{delivery_id}/report/decisions` |
| Descargar documento | `GET /api/delivery/runs/{delivery_id}/artifacts/{artifact_id}` |

La consulta del informe incluye Lead Time, Process Time, esperas registradas
y retrabajo, con desglose humano y agente. El tiempo de revisión humana sin
medición permanece sin clasificar. Cada PDF se conserva como instantánea.
