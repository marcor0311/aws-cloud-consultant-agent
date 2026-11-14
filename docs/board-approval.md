# Votación y acta de junta

Meeting Assistant exige unanimidad de cuatro o cinco miembros antes de crear el
repositorio. La decisión de encuadre, prioridad, presupuesto y arquitecto siguen
en PostgreSQL; la aprobación colegiada tiene su propia convocatoria y evidencia.

El poll usa botones **Aprobar**, **Rechazar** y **Abstenerse** en un mensaje de
Slack. Cada identidad del padrón tiene un voto. Duplicados no suman; un voto en
contra o una abstención impide aprobar. Una reconsideración requiere nueva ronda.
Los miembros de la demostración son **Board Member 1** a **Board Member 4**.

## Documento generado

Al recibirse el último voto, el servicio genera y conserva en PostgreSQL:

- `docs/02-board/acta-junta-<votacion_id>.md`: proyecto, resultado, regla,
  miembros, votos, fecha de cada voto y cierre en hora de Costa Rica, presupuesto,
  condiciones y hashes de los seis archivos, incluido el guion aprobado.
- `docs/02-board/acta-junta-<votacion_id>.json`: evidencia estructurada, fechas UTC,
  workspace, aplicación, canal, mensaje, hashes de las solicitudes verificadas y
  huella del certificado.

Los archivos se cargan junto con los insumos cuando se ejecuta la apertura. El
issue de arquitectura enlaza el acta del commit exacto. El acta es un registro de
la votación; no genera cobros ni facturas. Una decisión rechazada también produce
un acta de resultado, pero no habilita la apertura.

Al sellar un resultado `not_approved` (voto en contra o abstención), la misma
transacción registra una tarea `board_rejection` en la cola existente. El worker
principal debe usar la misma base y checkpoints PostgreSQL que el agente 2.
Al procesarla, verifica el certificado contra la apertura y vincula sus archivos
al manifiesto y la entrega de preparación aceptada. Esa revisión y su SHA-256
deben coincidir con la aprobación registrada en el proceso de seis etapas.
No crea un proceso ni una aprobación para completar datos faltantes.

La entrega aplica `stage.rejected` a Dirección, con `comment=not_approved` tomado
del certificado, `actor` del emisor persistido de la entrega del acta, y referencias
al certificado, su huella y los documentos del acta. El proceso y la apertura
quedan como `declined`; atender la cola omite esos expedientes. Un reintento usa
el mismo ID de evento y reconstruye las proyecciones sin repetir el rechazo,
incluso si el checkpoint se guardó antes del recibo de la tarea.

Si la correspondencia no es verificable, el voto y el acta permanecen intactos;
la tarea queda fallida con `receipt.status=blocked` y el motivo consultable en
`consultar_trazabilidad` / `audit`, en `board_workflow_delivery`. Después de
conciliar los registros se puede reintentar mediante el mecanismo existente de
tareas fallidas. No se envían correos ni nuevos mensajes Slack.

El acta cerrada no se modifica. La aprobación se vincula a la decisión, sus
partidas y versiones de archivos. Un cambio de paquete o una nueva convocatoria
invalida su uso para avanzar hasta completar la nueva unanimidad.

## Configuración de Slack

Configurar `SLACK_BOT_TOKEN` y `SLACK_SIGNING_SECRET` en el entorno privado.
En la aplicación Slack, activar Interactivity y configurar un callback HTTPS
para `POST /api/board/slack/actions`. La implementación aporta la ruta local;
no crea hosting ni túneles. No modifica el receptor exclusivo de Calendar.

El bot necesita `chat:write`, `users:read` y acceso al canal. Para conciliar un
envío incierto necesita el historial de ese canal (`channels:history` o
`groups:history`, según corresponda). La configuración de convocatoria incluye
workspace, aplicación, canal, IDs de miembros y un enlace HTTPS al paquete de
seis archivos aprobados que deben revisar. Los nombres visibles no sustituyen los IDs.

Herramientas MCP:

1. `preparar_votacion_junta(expediente_id, configuracion)`: fija padrón y versión;
   no envía mensajes ni registra votos. Repetir reutiliza la misma convocatoria.
   `nueva_ronda=true` inicia una reconsideración sin copiar los votos anteriores.
2. `publicar_votacion_junta(votacion_id)`: publica el poll con autorización expresa.
3. `consultar_votacion_junta(votacion_id)`: muestra progreso y resultado.
4. `consultar_acta_junta(votacion_id)`: devuelve los dos documentos al cerrar.
5. `conciliar_votacion_junta(votacion_id, mensaje_ts)`: verifica el mensaje de un
   envío incierto, sin repetirlo a ciegas.

No existe una herramienta MCP que emita votos por las personas. El callback
comprueba firma HMAC, ventana de cinco minutos e identidad de workspace,
aplicación, canal, mensaje y votante. Los votos se confirman en la base antes del
ACK; el refresco visual de Slack ocurre después. Los clics simultáneos se
serializan para no perder votos. Solo se admiten solicitudes firmadas para la
convocatoria correspondiente.

## Demostración sin Slack ni GitHub

```sh
make agent2-preview
```

Ejecuta LangGraph y PostgreSQL real aislado. Simula cuatro votos a favor, genera
acta y evidencia dentro del repositorio de previsualización en
`project/generated/meeting-assistant/preview-nike-01-lindora-run/repository/docs/02-board/`.
Los documentos están marcados **SIMULACIÓN**. Los votos simulados no autorizan
la apertura real por defecto. No se contactan Slack, GitHub ni modelos.

Para la prueba Nike el usuario autorizó expresamente `make agent2-live MOCK_BOARD=1`:
la votación es simulada, mientras OAuth, inferencia, MCP y GitHub son reales cuando
el usuario activa el comando. La autorización se registra con el ID de ejecución
y se limita al caso ficticio indicado. El acta conserva la marca de simulación;
no se atribuyen votos reales a miembros de junta ni se reemplazan votaciones reales.

Referencias: [verificación de solicitudes Slack](https://docs.slack.dev/authentication/verifying-requests-from-slack/),
[acciones de Block Kit](https://docs.slack.dev/reference/interaction-payloads/block_actions-payload/).
