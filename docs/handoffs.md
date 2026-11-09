# Trazabilidad de entregas

El caso mantiene el mismo `case_id` en preparación, proceso principal y apertura.
`workflow_handoffs` registra emisor, destinatario, fases, revisión, hash, creación,
recepción y actor receptor. `workflow_events` conserva los eventos de entrega y
aceptación. Los checkpoints de LangGraph viven en el mismo PostgreSQL.

La preparación registra transcripción → preparación → revisión del responsable.
Su aprobación crea la entrega a etapa 2. Un manifiesto `artifact-files` vincula la
revisión a los cuatro archivos exportados. El agente 2 exige ese manifiesto, acepta
la entrega y revalida la revisión antes de ejecutar. Una convocatoria publicada
crea una entrega por miembro; el voto firmado confirma su recepción. Al cerrarse
la votación se entrega el acta al agente 2. El issue genera la entrega al arquitecto,
que permanece pendiente hasta una aceptación expresa del destinatario.

El seguimiento de una cita verificada registra Calendar Assistant → responsable
de reunión. Una importación documental local no fabrica ese paso de voz/Calendar.

## Consulta

Desde `project/backend`:

```sh
.venv/bin/python -m app.cli.meeting_assistant audit --case nike-01-lindora-run
```

La herramienta MCP equivalente es `consultar_trazabilidad`. Muestra manifiesto,
procedencia, revisiones, entregas y eventos. El informe local de Nike queda en
`project/generated/meeting-assistant/handoff-audit-nike.json`.

## Conciliación del caso existente

Los documentos de Nike se habían generado en memoria y su apertura se había
registrado por separado. La conciliación incorporó la transcripción preparada,
el contenido validado y la aprobación expresa previa del usuario. Conservó los
cuatro archivos existentes y registró la incorporación con fecha actual,
`provenance=reconciled_local_documents` y `historical_occurred_at=null`.
No acredita una llamada, una reunión real ni votos de junta.

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
