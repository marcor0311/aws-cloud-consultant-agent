# Backend de Calendar Assistant

FastAPI mantiene los clientes pre-registrados y verifica a quien llama mediante
un OTP enviado exclusivamente al correo aprobado. El agente no crea registros,
no cambia correos ni recibe el correo aprobado en sus resultados de herramientas.

## Ejecutar

Desde la raíz del repositorio, con Python 3.10 o posterior:

```sh
# Solo en una instalación nueva: completar project/.env desde su ejemplo.
make setup-backend
make backend
```

Para procesar reuniones y preparación, abrir otra terminal en la raíz:

```sh
# Con WORKFLOW_ENABLED=1 en la configuración local existente.
make workflow
```

La API solo recibe operaciones y eventos; no inicia el worker. Mantener el mismo
modo y directorio de datos al iniciar `make preparation-mcp` o `make mock-mcp`.

Documentación interactiva: `http://127.0.0.1:8000/docs`.
El backend expone las rutas de verificación de clientes.
`app/notifications/templates/verification_code.html` es la plantilla activa del OTP. La oficina
virtual está en [`project/frontend/`](../frontend/README.md), separada de la API.

## Registro de empresas por negocio

El archivo `CALENDAR_ACCESS_DB` (predeterminado `data/calendar-access.sqlite3`,
relativo a `project/`) contiene la tabla `clients`, sesiones y límites de uso.
No guardar registros reales en Git. Crear empresas desde `project/backend/`:

```sh
.venv/bin/python -m app.cli.clients add --company-name "Empresa de ejemplo" --company-email "contacto@example.com"
```

La salida incluye únicamente `client_id` y `client_code`; negocio entrega el código
al cliente. No se envía correo al registrar. No hay API ni herramienta del agente
para crear clientes. El comando rechaza correos duplicados.

| Campo | Regla |
| --- | --- |
| `client_id` | Entero generado por SQLite con AUTOINCREMENT; identidad interna |
| `client_code` | Cuatro letras A–Z y cuatro dígitos, `XXXX-0000`, UNIQUE |
| `company_name` | Nombre de la empresa pre-registrada |
| `company_email` | Correo aprobado, normalizado y único |
| `enabled` | 1 habilitado; 0 impide verificar y revoca acceso al detectarse |

El servidor usa `secrets.choice` y `secrets.randbelow`, permite repeticiones, I,
O y ceros iniciales. Excluye Ñ. Comprueba si el código existe y reintenta ante
colisiones; la restricción UNIQUE y una transacción protegen altas simultáneas.
Tras 100 colisiones consecutivas falla sin crear un registro incompleto.
Hay 4 569 760 000 códigos posibles. El código identifica, nunca autentica.

Los registros de clientes se administran en SQLite mediante el comando anterior.
Al abrir una base de sesiones anterior se añade `client_code` y se invalidan las
autorizaciones anteriores, conservando el historial de límites.

## Configuración

Solo existe un `.env` local: `project/.env`. Las variables del proceso tienen
prioridad y el agente carga únicamente sus propias variables.

- `CALENDAR_ACCESS_SERVICE_KEY`: clave aleatoria de 32 caracteres o más, compartida
  con el servicio del agente; nunca con el navegador o el modelo.
- `CALENDAR_ACCESS_CODE_SECRET`: secreto distinto, de 32 caracteres o más,
  exclusivo del backend para los HMAC de los OTP.
- `CALENDAR_ACCESS_DB`: base SQLite en almacenamiento persistente privado.
- `CALENDAR_MAIL_PROVIDER`: `smtp` (predeterminado) o `gmail`.
- SMTP: `CALENDAR_SMTP_HOST`, `CALENDAR_SMTP_PORT` (587),
  `CALENDAR_SMTP_SECURITY` (`starttls` o `ssl`), `CALENDAR_SMTP_FROM`;
  opcionalmente `CALENDAR_SMTP_USERNAME`, `CALENDAR_SMTP_PASSWORD` y
  `CALENDAR_SMTP_SENDER_NAME`.
- Agente: `CALENDAR_ACCESS_URL=http://127.0.0.1:8000/api/calendar-access` y
  `CALENDAR_ACCESS_ORIGIN_ID=calendar-assistant`.

Generar cada secreto por separado con
`python -c 'import secrets; print(secrets.token_urlsafe(32))'`.

## Enviar con Gmail API

Con Gmail no se necesitan contraseña de correo ni credenciales SMTP. Habilitar
Gmail API en el mismo proyecto de Google Cloud que utiliza el cliente OAuth.
Configurar el proveedor y las rutas en `project/.env`; la cuenta se guarda en
el `secrets.env` externo:

```dotenv
CALENDAR_MAIL_PROVIDER=gmail
GOOGLE_ACCOUNT_EMAIL=<cuenta de Google autorizada>
CALENDAR_GMAIL_CLIENT_FILE=google/oauth-client.json
CALENDAR_GMAIL_TOKEN_FILE=google/gmail-token.json
```

Desde la raíz del repositorio, autorizar una vez:

```sh
make gmail-auth
```

El navegador solicita el permiso `gmail.send` para la cuenta configurada. El
usuario debe aceptar el consentimiento de Google; habilitar la API no concede
este permiso. No se solicita lectura del buzón. El cliente OAuth puede reutilizarse,
pero el token de envío se guarda por separado en el directorio privado externo, fuera de
Git y con permisos 600. El token de Calendar no se modifica.

Gmail envía desde la cuenta autorizada o sus alias permitidos. Seleccionar esa
misma cuenta en el consentimiento. El backend reutiliza la plantilla HTML y la
alternativa de texto, renueva tokens vencidos y exige el identificador de aceptación
de Gmail antes de informar éxito. No reintenta automáticamente un envío ambiguo.
Se conservan los límites de códigos y reenvíos; también aplican las cuotas de Gmail.

Si la herramienta del agente devuelve `unavailable`, revisar la terminal del
backend: `OTP email delivery failed` muestra el diagnóstico seguro del proveedor.
`gmail_oauth_refresh_rejected` con `invalid_grant` indica que Google rechazó
renovar la autorización de Gmail. Ejecutar de nuevo `make gmail-auth`, completar
el consentimiento y volver a intentar la verificación respetando la espera entre
envíos. `make calendar-auth` autoriza otro token y no recupera el envío de correo.
Los detalles OAuth se conservan fuera de la respuesta pública; los logs no incluyen
el OTP, el destinatario ni el cuerpo privado de la respuesta de Google.

## Verificación y pruebas

`GET /health` comprueba juntas las autorizaciones OAuth de Calendar, Gmail si es
el proveedor seleccionado y Google del workflow real si está habilitado:

```sh
curl -sS http://127.0.0.1:8000/health
```

Devuelve `200` con `status=ok`, o `503` con `status=degraded` y un diagnóstico por
integración: `code`, `message` y `action` con el comando para recuperar la
autorización. También revisa que las claves locales de verificación estén
configuradas y sean independientes. Los componentes desactivados figuran como
`skipped`. Los resultados OAuth se reutilizan por hasta treinta segundos; cambiar
el archivo de token invalida su resultado anterior. Un token compartido por
Calendar y workflow se comprueba una sola vez por intervalo.

La prueba renueva el acceso únicamente en memoria. No guarda tokens, envía OTP,
consulta agendas, crea citas ni ejecuta inferencia. No certifica cuotas ni el
funcionamiento completo de las API, SMTP o los modelos; el campo `scope` indica su
alcance. `GET /` conserva su respuesta básica y no realiza comprobaciones externas.

El flujo, los contratos y los límites están en
[Verificación del cliente](../agents/1.%20calendar%20assistant/VERIFICACION_CORREO.md).
La plantilla `app/notifications/templates/verification_code.html` contiene el OTP, vigencia y aviso de
seguridad; también se envía una alternativa de texto simple. Gmail y SMTP usan
la misma plantilla.

Desde la raíz del repositorio:

```sh
make test-backend
```

Desde `project/agents/1. calendar assistant/`:

```sh
uv run pytest -q
uv run ruff format --check src tests demos
uv run ruff check src tests demos
```

La suite reducida conserva cuatro recorridos de integración: acceso/OTP,
transcripción y persistencia, preparación→agente 2→handoffs, y OAuth→LangGraph→MCP.
Usa almacenamiento temporal y proveedores ficticios; no consume inferencia.
Los casos unitarios redundantes y las comprobaciones de estructura se eliminaron.
Para el recorrido completo o PostgreSQL aislado, ejecutar bajo demanda
`make test-e2e` o `make test-postgres`. Ver [criterio y comandos](../../docs/testing.md).

## Organización del backend

- `app/clients/`: identidad y generación de códigos en `domain.py`; SQLite en
  `repository.py`.
- `app/verification/`: servicio OTP sin SQL, contratos, repositorio SQLite y schemas; los endpoints están
  en `app/api/calendar_access.py` y las dependencias HTTP en `app/api/dependencies.py`.
- `app/notifications/`: renderizado del mensaje, plantilla y adaptadores Gmail y
  SMTP; `provider.py` selecciona el proveedor configurado.
- `app/core/`: configuración local y validación común de correo.
- `app/workflow/`: estado, transiciones deterministas, grafo principal de seis
  etapas y servicio compartido por HTTP/MCP.
- `app/preparation/`: grafo posterior a la reunión, estado, nodos, modelos y
  servicios; sus colaboradores se inyectan desde `app/bootstrap.py`.
- `app/persistence/`: SQL compartido, savers de checkpoints y bloqueo local.
- `app/integrations/`: Google, Slack, IA y mocks; OAuth de la demo en `ai/oauth.py`.
- `app/api/` y `app/mcp_server.py`: entradas sobre los mismos servicios.
- `app/worker.py`: bucle del único worker; `app/workflow/runtime.py` despacha tareas.
- `app/demos/`: demostraciones con sus interfaces; `app/cli/` mantiene lanzadores pequeños.
- `app/cli/`: registro administrativo de empresas y consentimiento de Gmail.
- `tests/`: integraciones esenciales y recorrido completo opcional.

El agente solo usa la API HTTP. No recibe el OTP generado ni las credenciales de
envío. La plantilla se conserva con el código que la renderiza en el backend.
La autorización de Calendar pertenece al agente y usa otro archivo de token.

Consultar [la arquitectura](../../docs/architecture.md) para los contratos entre
componentes y las reglas de dependencia.

## Workflow de seis etapas

### Preparación en segundo plano y `/prepare`

El procesador actual reutiliza el generador corporativo y publica `resumen-reunion.pdf`,
`ficha-proyecto.pdf`, `presentacion.html`, `presentacion.pdf` y `transcripcion.pdf` en `insumos/<case_id>/`, carpeta excluida de Git. La respuesta
MCP incluye los cinco nombres y rutas para abrirlos. No genera guion ni
preguntas de descubrimiento. La transcripción es la fuente completa del contenido.
Ver [contrato y lectura de documentos](../../docs/insumos.md).

Al recibir una transcripción correlacionada, el worker guarda una tarea durable de
preparación aunque no exista API key. En su mantenimiento recupera también las
transcripciones anteriores sin preparación, sin duplicar tareas ni revisiones.
Esto incluye checkpoints del flujo interactivo anterior pausados en
`draft_with_chatgpt`: el worker los reanuda con el proveedor configurado,
conservando la transcripción, las notas, la identidad de entrada y la revisión.
No reanuda automáticamente las pausas de aprobación de presentación o guion.
`make workflow` debe permanecer ejecutándose: el servidor MCP no arranca el worker.

La generación se basa exclusivamente en la transcripción y las notas del proyecto;
no importa un catálogo, busca antecedentes ni compara otros proyectos. Los
proveedores y el contrato de documentos no incluyen proyectos relacionados.

El proveedor predeterminado es `WORKFLOW_PREPARATION_PROVIDER=chatgpt`. Reutiliza
la sesión privada creada con `make agent2-login`, renueva OAuth y consume el modelo
seleccionado en `WORKFLOW_OPENAI_MODEL`, sin fallback a API key. La generación real
permanece desactivada hasta la activación explícita `WORKFLOW_INFERENCE_ENABLED=1`.
No activar ni ejecutar inferencia real durante comprobaciones rutinarias: cada
ejecución real requiere autorización del usuario. Para usar el adaptador histórico
de API de manera deliberada, seleccionar `WORKFLOW_PREPARATION_PROVIDER=api`.

Para el túnel privado, guardar `PREPARATION_MCP_BEARER_TOKEN` (al menos 32 caracteres)
en `secrets.env` y ejecutar `make preparation-http`. El destino local es
`http://127.0.0.1:8769/mcp`, separado del agente 2 en el puerto 8768. Configurar el
Secure MCP Tunnel y la autenticación de la conexión con ese destino; su identidad
y credenciales se mantienen fuera del repositorio.

La herramienta `prepare(proyecto_id="")` lista proyectos; con ID consulta el
trabajo existente. Distingue `queued`, `processing`, `blocked`, `paused`, `idle` y los estados
de revisión/aprobación. Devuelve errores de tarea y documentos persistidos; una
consulta no invoca el modelo ni encola trabajo. `actualizar_insumos` conserva
la edición conversacional como una revisión nueva sin aprobarla.
`paused` identifica una espera de borrador interactivo anterior sin tarea activa;
el worker recupera esa espera durante mantenimiento.

Se puede invocar el mismo MCP desde terminal sin ChatGPT, plugin ni túnel:

```sh
make prepare                       # Lista los proyectos
make prepare CASE=<id-del-proyecto> # Consulta su progreso y documentos
```

Este cliente abre un servidor MCP STDIO local, inicializa la sesión e invoca la
herramienta `prepare`; no llama directamente al servicio del backend. Cierra el
servidor al terminar la consulta. La generación sigue en el worker independiente
(`make workflow`), con la activación expresa y la sesión OAuth configuradas.
`make preparation-mcp` solo arranca el servidor STDIO para otros clientes MCP;
no es una consola interactiva donde escribir `/prepare`.

El paquete local `plugins/aws-cloud-consultant/` incluye la skill `prepare` para
la invocación `/prepare` en clientes compatibles. No está instalado ni enlazado a
una cuenta: después de registrar el MCP privado en ChatGPT, enlazar el plugin con
su ID técnico real (`plugin_asdk_app...`) e instalar el paquete. No confundir ese
ID con el nombre o el ID del túnel. Una herramienta MCP llamada `prepare` por sí
sola no registra un comando slash en la interfaz de ChatGPT.

Referencias: [inferencia OAuth](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference),
[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels),
[paquete y enlace del plugin](https://developers.openai.com/plugins/build/plugins).

El worker enlaza la reunión confirmada con el cliente existente, espera la
transcripción de la reunión terminada, prepara los insumos y solicita la revisión.
El estado del proceso se consulta con `consultar_proceso` en MCP o
`GET /api/workflow/cases/{case_id}/process`, usando la credencial del operador.
Las herramientas existentes de preparación conservan sus contratos de aprobación.
Las solicitudes de inicio, regeneración y reanudación devuelven `task_id` y se
procesan con `make workflow`; `consultar_integraciones` muestra los fallos y estados.

Para las siguientes etapas, `registrar_evento_proceso` y
`POST /api/workflow/cases/{case_id}/process/events` llaman al mismo servicio. El
contrato de una decisión es, por ejemplo:

```json
{
  "event_id": "decision-direccion-001",
  "kind": "stage.approved",
  "stage": 2,
  "iteration": 2,
  "revision": 1,
  "artifact_sha256": "<SHA-256 de la versión pendiente obtenido al consultar el proceso>",
  "comment": "Decisión expresa de continuar con el proyecto"
}
```

Consultar siempre la etapa, iteración y versión actuales antes de decidir. Los
tipos admitidos al operador son `meeting.completed`, `deliverable.ready`,
`stage.approved`, `stage.changes_requested` y `stage.rejected`. Un
`deliverable.ready` requiere revisión creciente, SHA-256 y `evidence` con las
referencias al documento/commit. Las decisiones requieren la revisión y hash
exactos; las devoluciones y rechazos también requieren un motivo. FinOps devuelve
a arquitectura; las otras solicitudes de cambios conservan su etapa. Solo
dirección puede rechazar el proyecto. La aprobación del informe cierra el proceso.

Los eventos de transcripción y aprobación de preparación son internos y no se
admiten desde este endpoint. Las solicitudes HTTP devuelven `202`; el worker valida
de nuevo la decisión para impedir aprobaciones obsoletas. El uso local actual
corresponde a un operador autenticado, sin un sistema de permisos por puesto.
Las etapas 2–6 coordinan entregas externas: no ejecutan sus agentes ni integran
PRs automáticamente. La demo OAuth en `app/demos/chatgpt.py` sigue siendo una prueba separada;
el proveedor de preparación se inyecta a través del contrato `DraftGenerator`.


Los comandos internos principales son `python -m app.worker` y
`python -m app.mcp_server`, desde `project/backend/`. Los aliases de `make`
conservan sus nombres. Al actualizar una configuración externa de MCP, usar
`app.mcp_server` como módulo; los nombres y schemas de sus herramientas permanecen.


El SQL de OTP está en `app/verification/repository.py`; los servicios reciben
`VerificationRepository`. Las operaciones de continuidad de los grafos se reciben
por `WorkflowExecution` (`app/workflow/ports.py`) y su adaptador está en
`app/integrations/langgraph.py`. El schema OTP y los thread IDs existentes se conservan.

## Credenciales locales

`project/.env` contiene configuración no sensible. `CLOUD_CONSULTANT_SECRETS_DIR`
apunta por defecto a `~/.config/aws-cloud-consultant-agent/dev/`, donde viven
`secrets.env`, credenciales Google y sesiones ChatGPT. Los valores del proceso
tienen prioridad; las rutas de credenciales relativas usan esa raíz privada.
Ver [estructura de ejemplo y migración](../../config/local-secrets.example/README.md).

`make setup-backend` también instala Playwright y su Chromium compatible para
exportar la presentación PDF desde HTML, sin depender de Chrome del sistema.
En Linux mínimo puede requerirse `python -m playwright install-deps chromium`
dentro del entorno del backend; ver [generación de insumos](../../docs/insumos.md).
