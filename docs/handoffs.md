# Trazabilidad de entregas

El caso mantiene el mismo `case_id` en preparación, proceso principal y apertura.
`workflow_handoffs` registra emisor, destinatario, fases, revisión, hash, creación,
recepción y actor receptor. `workflow_events` conserva los eventos de entrega y
aceptación. Los checkpoints de LangGraph viven en el mismo PostgreSQL.

La preparación registra transcripción → preparación → revisión de presentación →
generación local del guion → revisión del guion. La primera aprobación no crea
la entrega: el guion queda en una nueva revisión pendiente de aprobación expresa.
Su aprobación crea la entrega a etapa 2. Un manifiesto `artifact-files` vincula la
revisión a los seis archivos exportados, incluido el guion. El agente 2 exige ese manifiesto, acepta
la entrega y revalida la revisión antes de ejecutar. Una convocatoria publicada
crea una entrega por miembro; el voto firmado confirma su recepción. Al cerrarse
la votación se entrega el acta al agente 2. El issue genera la entrega al arquitecto,
que permanece pendiente hasta una aceptación expresa del destinatario.

El seguimiento de una cita verificada registra Calendar Assistant → responsable
de reunión. Una importación documental local no fabrica ese paso de voz/Calendar.

La generación registra `preparation.speaker_notes_generated`, revisión origen y
SHA-256 de presentación. Las decisiones `approval.decided` indican `subject`.
La conciliación de una aprobación previa de presentación deja el nuevo guion
pendiente; no reutiliza esa aprobación para autorizar contenido recién generado.
El guion se consulta como `speaker-notes.md` en el MCP de preparación y viaja como
sexto archivo del paquete. Antes de aprobar la presentación se vinculan sus cinco
archivos con `registrar_archivos_presentacion`; después de aprobar el guion se usa
`exportar_paquete_aprobado`. La exportación conserva los bytes aprobados en
`approved/<case_id>/v<revision>/`, registra hashes y revisión y añade `manifest.json`.
El agente 2 publica ese mismo paquete y enlaza el manifiesto en el issue de Arquitectura.
Los manifiestos antiguos de cuatro o cinco archivos se conservan; no habilitan
aperturas nuevas incompletas ni se amplían sin una nueva aprobación.

## Consulta

Desde `project/backend`:

```sh
.venv/bin/python -m app.cli.meeting_assistant audit --case nike-01-lindora-run
```

La herramienta MCP equivalente es `consultar_trazabilidad`. Muestra manifiesto,
procedencia, revisiones, entregas y eventos. El informe local de Nike queda en
`project/generated/meeting-assistant/handoff-audit-nike.json`.

El resultado negativo de junta se entrega por la cola al proceso principal:
Dirección termina como `declined`. El Engagement Manager lo consulta en
`consultar_proceso` o `GET /api/workflow/cases/<case_id>/process`, con el historial
`stage.rejected` y sus referencias al acta/certificado. La trazabilidad de agente 2
incluye `process` y `board_workflow_delivery` (tarea pendiente, recibo de entrega o
motivo de bloqueo). Estos canales no generan avisos nuevos. Una correspondencia
no verificable conserva la decisión de junta y bloquea su entrega al proceso.

## Conciliación del caso existente

Los documentos de Nike se habían generado en memoria y su apertura se había
registrado por separado. La conciliación incorporó la transcripción preparada,
el contenido validado y la aprobación expresa previa del usuario. Conservó los
cuatro archivos existentes y registró la incorporación con fecha actual,
`provenance=reconciled_local_documents` y `historical_occurred_at=null`.
No acredita una llamada, una reunión real ni votos de junta. La ampliación
posterior autorizada añadió la presentación PDF al manifiesto de cinco archivos.

El caso activo tiene tres entregas recibidas y permanece en cola, pendiente de
votación real. El recorrido completo con cuatro miembros ficticios se verifica en
otra base PostgreSQL mediante `make agent2-preview`; sus votos no habilitan GitHub
real por defecto. El usuario autorizó después la excepción `make agent2-live MOCK_BOARD=1`
para probar Nike con votos simulados y OAuth/MCP/GitHub reales; queda registrada
por ejecución y conserva las actas marcadas como simulación.
La prueba PostgreSQL también crea un caso aislado, interrumpe la apertura
y la reanuda desde otro runtime sin duplicar entregas.

## Consumo

Las pruebas y previews usan contenido preparado y proveedores simulados. No
inician LiveKit ni inferencia. La voz requiere `LIVEKIT_INFERENCE_ENABLED=1`;
la preparación real requiere `WORKFLOW_INFERENCE_ENABLED=1` en la ejecución
activada por el usuario. La redacción de agente 2 requiere `draft --allow-inference`.
Mantener esas opciones desactivadas durante las verificaciones.
