# 2. Meeting Assistant

Recibe una decisión expresa y abre el proyecto para Arquitectura. La reunión de
dirección y su evaluación previa se implementarán después. El runtime se ejecuta
con LangGraph desde el backend, con persistencia y checkpoints en PostgreSQL.

## Identidad de los proyectos

Los nuevos repositorios son públicos por defecto (`private=false`). Una decisión
aprobada puede solicitar explícitamente un repositorio privado. Este valor se
persiste en el expediente: cambiar el predeterminado no altera aperturas anteriores.

Todos los templates usan la misma convención:

```text
AWS Cloud Consulting Project <Compañía> <NN> <Proyecto>
aws-cloud-consulting-project-<compañía>-<nn>-<proyecto>
```

El segundo es el nombre de GitHub: minúsculas, sin tildes y con guiones. El número
se reserva consecutivamente por compañía en la base de datos. Ejemplo:
`AWS Cloud Consulting Project Nike 01 Lindora Run` y
`aws-cloud-consulting-project-nike-01-lindora-run`.

## Ejecución local

Configurar `WORKFLOW_DATABASE_URL` de PostgreSQL en el `secrets.env` externo. Se usa la misma
base para decisiones, cola, mediciones, handoffs y checkpoints; no se modifica la
base de clientes/OTP. GitHub utiliza `GITHUB_TOKEN`, `GH_TOKEN` o la sesión de
`gh auth login`; necesita crear desde template, publicar contenido, invitar/asignar
al responsable y crear issues y pull requests. El inicio de sesión de ChatGPT es independiente.

Desde la raíz:

```sh
make agent2-login     # Continue with ChatGPT; no genera texto ni consume inferencia
make agent2           # MCP privado por STDIO
make agent2-preview   # Mismo LangGraph y PostgreSQL aislado; cero llamadas a GitHub
make agent2-register  # Registra la decisión explícita del caso Nike
make agent2-queue     # Lee prioridad, presupuesto y comentarios desde PostgreSQL
make agent2-run       # Ejecuta la primera apertura pendiente
make agent2-logout    # Revoca la sesión renovable y elimina credenciales locales
```

La decisión de encuadre de Nike está en
`backend/fixtures/nike-lindora-stuart/opening.json`: prioridad inicial 1,
presupuesto de USD 180.000 con sus cinco partidas, arquitecto `HiddenShadow77UC`
y hashes de cinco archivos de presentación en `insumos temporales de agente 1/`.
Ese fixture histórico no autoriza una apertura nueva incompleta: la CLI incorpora
el guion desde el manifiesto de seis archivos de la revisión aprobada.
Se conserva su identificación como escenario ficticio.

## Flujo y entrega

`registrar_apertura` comprueba la entrega aprobada de preparación, su revisión y
el manifiesto de seis archivos, incluido `speaker-notes.md` aprobado, registra su recepción y reserva el número.
Una decisión aislada ya no puede saltarse esa entrega. La apertura exige
además la unanimidad de la junta, registrada mediante votos firmados de Slack. `ejecutar_apertura`
crea desde `marcor0311/aws-cloud-consulting-project-template`, conserva carpetas
numeradas, publica los seis insumos y `manifest.json` en `docs/01-discovery/` junto con README
y la plantilla de issue, en la rama `docs/initial-structure`. Abre un PR hacia la rama principal y verifica
su merge antes de crear el issue de Arquitectura. El cuerpo del issue
siempre se obtiene de `templates/architecture.md`; los enlaces de evidencia
apuntan al commit exacto. No se publican prioridad ni comentarios de dirección.

`agent2-preview` requiere `MEETING_ASSISTANT_PREVIEW_DATABASE_URL`, distinta de la
base activa. Escribe el issue y la estructura propuesta en
`project/generated/meeting-assistant/preview-nike-01-lindora-run/`, con un informe
explícito de simulación. No llama a GitHub ni a modelos. Sus URLs usan
`github.invalid` y no representan repositorios reales.

Los pasos se recuperan desde checkpoints. Los hashes detectan cambios posteriores
a la aprobación. Una respuesta perdida de GitHub se concilia antes de repetir:
se comprueban el marcador del repositorio, los blobs del commit y el marcador
del issue, incluso si está cerrado. Una invitación pendiente al arquitecto conserva
el issue creado y pausa la entrega con `architect_invitation_pending`; después de aceptarla, repetir el
mismo comando reanuda el flujo. No se crea otro repo ni se marca la entrega como
completada sin comprobar la asignación.

Las herramientas MCP son `registrar_apertura`, `consultar_trazabilidad`, `consultar_cola_proyectos`,
`consultar_apertura`, `ejecutar_apertura` y `atender_siguiente_proyecto`. También
se exponen preparación, publicación, consulta y conciliación de la votación, y
consulta del acta. No se expone una herramienta para votar por los miembros.
Ver [configuración y actas de junta](../../../docs/board-approval.md).
Ver [trazabilidad desde preparación](../../../docs/handoffs.md).
El adaptador GitHub implementa la operación oficial de generar desde template,
incluida la carga binaria de los PDF, detrás de esas herramientas.

## Uso del modelo y sesiones

### Apertura real desde LangGraph con el plan de ChatGPT

Desde la raíz, para la prueba Nike autorizada por el usuario:

```sh
make agent2-live MOCK_BOARD=1
```

Este comando **consume el plan de ChatGPT y publica en GitHub real**. Genera
cuatro votos Slack simulados y acta marcada como simulación para este caso
ficticio. No envía mensajes a Slack. Reutiliza la sesión OAuth de agente 2 o abre
Continue with ChatGPT si falta. GitHub usa su propia sesión `gh auth login` o
`GITHUB_TOKEN`; las credenciales de ChatGPT no conceden acceso a GitHub.

Sin `CASE=...`, lee de PostgreSQL el primer expediente pendiente según la cola.
El nombre y correlativo ya están reservados en el registro del expediente; el
modelo no los inventa. Una ejecución con `EXECUTION_ID` existente recupera su
expediente original aunque la cola haya cambiado. Puede elegirse un expediente
expresamente con `CASE=<id>`. Reintentar no reserva un número ni otro repo.

Después de generar desde template, el adaptador permite hasta 20 segundos de
espera acumulada si la rama devuelve 404/409 mientras se inicializa. Lee
la rama actual desde los metadatos y no inicializa un repo vacío ni recrea el repo.
Si sigue sin estar disponible, conserva el checkpoint y pide reanudar el mismo ID.

El grafo persistido ejecuta `mcp_preflight → chatgpt_oauth → mcp_github_opening`.
El nodo del modelo usa OAuth y Responses con la definición de herramienta recibida
por MCP. Su llamada validada se envía por un cliente MCP STDIO al servidor privado
Meeting Assistant; este ejecuta el grafo de apertura y el adaptador REST de GitHub.
Es un intercambio MCP real con el servidor del proyecto, no el servidor oficial
GitHub MCP. El resultado incluye repo desde template, los insumos aprobados, acta y
issue asignado a David.

Se guardan `response_id`, modelo, `usage`, nombre y argumentos de herramienta,
identidad del servidor MCP, versión de protocolo y recibos de GitHub en PostgreSQL
y `project/generated/meeting-assistant/live-<execution-id>.json`. Sin respuesta
completa y uso positivo reportado no se declara éxito ni se publica.

`MODEL=auto` toma el primer modelo visible del catálogo de la cuenta. Puede
seleccionarse uno expresamente con `MODEL=<id>`. Cada ejecución nueva hace una
inferencia; para reanudar sin repetir una inferencia confirmada:

```sh
make agent2-live MOCK_BOARD=1 EXECUTION_ID=<id-impreso-al-iniciar>
```

Si el consumo quedó incierto antes de poder registrarse, el mismo ID bloquea su
repetición automática. Un ID nuevo autoriza otro intento con posible consumo.
Sin `MOCK_BOARD=1` se exige la votación real. La excepción no sirve para casos
reales y no sustituye una votación real existente. `agent2-run` conserva ese bloqueo.

La apertura de un encargo ya aprobado es determinista: el modelo no vuelve a
decidir prioridad, inversión ni responsable. Para redactar un encargo nuevo
con el plan de ChatGPT, autorizar esa ejecución concreta:

```sh
cd project/backend
.venv/bin/python -m app.cli.meeting_assistant draft \
  --model MODELO_DISPONIBLE_EN_TU_CUENTA \
  --transcript fixtures/nike-lindora-stuart/transcript.md \
  --output ../generated/architecture-work.json --allow-inference
```

El resultado queda pendiente de revisión y no crea repositorios ni issues.
Las sesiones usan PKCE, validación de identidad y scopes, persistencia privada
0600 y rotación serializada de refresh tokens. Las credenciales se guardan en
`~/.config/aws-cloud-consultant-agent/dev/chatgpt/meeting-assistant/`; no se guardan en PostgreSQL ni GitHub.
Logout informa si no pudo confirmar la revocación remota. No hay fallback a API key.

Referencias oficiales: [Sign in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
[sesiones y cierre](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions),
[crear desde template](https://docs.github.com/en/rest/repos/repos#create-a-repository-using-a-template).

## Verificación

```sh
cd project/backend
.venv/bin/python -m pytest -q tests/project_opening
.venv/bin/ruff check app tests
.venv/bin/ruff format --check app tests
```

Las pruebas ordinarias son offline. La prueba opcional con PostgreSQL real usa
`WORKFLOW_TEST_POSTGRES_URL` aislada y simula todos los efectos en GitHub.

## Apertura en la organización

Los nuevos expedientes usan `owner=aws-cloud-consulting-group`; el template sigue
siendo `marcor0311/aws-cloud-consulting-project-template`. El paquete se publica
solo en `docs/initial-structure`, sin force push. El agente concilia el PR por
rama, base, marcador y SHA; intenta fusionarlo sin alterar las protecciones y
verifica `merged` antes de crear el issue. Si faltan revisiones, permisos o checks,
queda en `awaiting_initial_structure_merge`; reanudar el mismo expediente retoma
ese PR sin duplicar el paquete. Un PR modificado o cerrado sin merge requiere
conciliación. El SHA aprobado se conserva como referencia de los insumos.

El fixture Nike mantiene a `HiddenShadow77UC` como arquitecto previsto y usa
`issue_assignee=marcor0311` como responsable temporal del issue. La asignación
temporal no acredita aceptación del arquitecto: su handoff sigue pendiente.
En otros expedientes `issue_assignee` es opcional y por defecto se asigna al arquitecto.

Cambiar el fixture no cambia expedientes ya persistidos. Eliminar el repo personal
no elimina su registro, checkpoint ni entrega. Antes de volver a ejecutar Nike,
conciliar explícitamente el destino y el estado histórico; el registro rechaza
reemplazar silenciosamente una decisión con otro hash. No usar otro ID para
sortear esto ni reservar otro correlativo. Los checkpoints anteriores que llegan
al paso de asignación sin un PR fusionado también exigen conciliación.

El paquete actual incluye `presentacion.html` y `presentacion.pdf` (una diapositiva por página), además de los dos PDF ejecutivos y la transcripción. `make setup-backend` instala Playwright y Chromium para exportar el PDF; `requirements-artifacts-dev.txt` añade las herramientas de revisión visual. `INSUMOS_BROWSER` permite elegir otro Chromium. El editor HTML usa `storageSlot` para su identificador de localStorage; no contiene credenciales. El paquete define Markdown con prosa sin límite de 80 columnas, etiquetas de interlocutor en negrita y títulos de frontmatter independientes del H1. Gitleaks mantiene el análisis completo del historial.

La raíz privada se configura mediante `CLOUD_CONSULTANT_SECRETS_DIR`. Ver [ejemplos y migración](../../../config/local-secrets.example/README.md).

Las aperturas y entregas nuevas exigen seis archivos: los cinco originales y el
guion aprobado (`speaker-notes.md`). Preparación vincula primero los archivos de
presentación y, tras aprobar también el guion, exporta a
`approved/<case_id>/v<revision>/` mediante `exportar_paquete_aprobado` o la CLI
`app.cli.preparation_documents export`. Se conservan los bytes, los hashes y la
revisión; el issue enlaza el manifiesto del commit publicado. Los reintentos no
regeneran ni sobrescriben el guion. La compatibilidad con cuatro o cinco archivos
se limita a expedientes y manifiestos ya persistidos: no permite registrar una
apertura nueva incompleta.
