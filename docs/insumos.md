# Procesador documental corporativo

El worker procesa la transcripción completa de Stuart como fuente del proyecto y
publica exactamente cinco archivos en `insumos/<case_id>/`, en la raíz:

- `resumen-reunion.pdf`: objetivo, problema, alcance, necesidades, requisitos,
  integraciones, restricciones, presupuesto, plazos, riesgos y decisiones.
- `ficha-proyecto.pdf`: síntesis ejecutiva del encargo, límites, inversión y plazos.
- `presentacion.html`: presentación corporativa autónoma, con fuentes locales.
- `presentacion.pdf`: las mismas diapositivas, impresas desde el HTML con Chromium.
- `transcripcion.pdf`: texto íntegro, en orden, sin resumir ni sustituir palabras.

Se reutiliza el generador corporativo `integrations/insumos_export.py`, la plantilla
`insumos_assets/presentation.html` y Lato. La referencia visual vigente está en
`insumos temporales de agente 1/` y `docs/design/`; no es un exportador retirado.
`ProcessedMeeting.corporate_insumos` adapta el contenido a `MeetingTranscript` y
`MeetingInsumos`. No rellena métricas, fechas, participantes, recomendaciones ni
compromisos ausentes. Las diapositivas extensas se distribuyen en continuaciones
con las composiciones existentes, conservando todos sus puntos.
`processed_documents.py` solo publica y registra los archivos del generador
corporativo; ya no contiene maquetación alternativa.

El procesador no añade descubrimiento, preguntas, entrevistas, recomendaciones,
comparaciones ni guion. Conserva lo no acordado con ese significado. La fuente
sintética se identifica como material ficticio y no acredita una reunión real.
Las notas anteriores permanecen guardadas; el proveedor actual usa la transcripción
y las instrucciones explícitas de revisión. El renderizado es local, sin inferencia.

`insumos/` está excluida de Git. Cada carpeta contiene únicamente los cinco archivos;
los hashes y datos de control se guardan en SQL. `prepare` solo consulta y devuelve
estado, identificador, revisión, nombres, rutas absolutas y carpeta. No inicia ni
duplica trabajos, y no devuelve por defecto el checkpoint o el paquete interno.
El MCP funciona desde terminal por STDIO y por HTTP privado sin ChatGPT abierto.
El worker debe estar ejecutándose para procesar nuevas transcripciones.

```sh
make prepare CASE=<case_id>
open "insumos/<case_id>/resumen-reunion.pdf"
open "insumos/<case_id>/ficha-proyecto.pdf"
open "insumos/<case_id>/presentacion.html"
open "insumos/<case_id>/presentacion.pdf"
open "insumos/<case_id>/transcripcion.pdf"
```

La publicación termina antes de notificar `awaiting_review`. Antes de aprobar se
verifican de nuevo los hashes de los archivos; la aprobación expresa acepta los
cinco como conjunto sin guion ni otra revisión. Los mismos bytes aprobados quedan
en SQL para la entrega al agente 2, junto con su manifiesto y la revisión.
Los contratos anteriores de tres archivos y los de cuatro/cinco/seis archivos con
transcripción Markdown y eventual guion conservan sus manifiestos y aprobaciones.
No se migran automáticamente expedientes ya aprobados.

Para reexportar una revisión pendiente usando el contenido ya guardado, sin modelo:

```sh
cd project/backend
WORKFLOW_INFERENCE_ENABLED=0 .venv/bin/python -m app.cli.workflow preparation-render \
  --case <case_id> --revision <revision-pendiente>
```

Crea una revisión nueva para revisión humana, conserva la fuente y los registros
anteriores y usa el mismo publicador del worker. Cada nueva llamada real al modelo
requiere autorización expresa por ejecución; reexportar no la realiza.

## Compatibilidad con la preparación anterior

Las secciones siguientes documentan también el flujo previo de citas, notas y guion.
Ese flujo se conserva para expedientes existentes; no define los entregables del
procesador actual ni convierte el generador corporativo en un sistema retirado.

## Preparación con notas de reunión

El Engagement Manager puede aportar la transcripción y las notas como textos
independientes. Las notas son opcionales y distintas de `speaker_notes`, el guion
que se genera después de aprobar la presentación. La generación usa únicamente
esas dos fuentes: no busca, cita ni compara proyectos anteriores. El campo
`consulta`/`--query` se conserva por compatibilidad con la identidad de las entradas
persistidas; no ejecuta una búsqueda ni aporta fuentes adicionales al modelo.

Desde MCP, `iniciar_preparacion` acepta:

```json
{
  "expediente_id": "expediente-existente",
  "evento_id": "reunion-terminada",
  "transcripcion": "Cliente: necesitamos ventas en línea; el presupuesto se confirmará.",
  "notas_reunion": "Stuart propone revisar los costos operativos cada mes.",
  "consulta": "ventas comercio electrónico"
}
```

Desde CLI, los dos archivos son texto UTF-8. El comando encola la preparación
para el worker; no ejecuta inferencia en la terminal:

```sh
cd project/backend
.venv/bin/python -m app.cli.workflow preparation-start \
  --case expediente-existente --event reunion-terminada \
  --transcript /ruta/transcripcion.txt \
  --meeting-notes /ruta/notas-reunion.md \
  --query 'ventas comercio electrónico'
```

Se requiere `WORKFLOW_ENABLED=1`, un expediente del responsable configurado y el
worker habitual (`make workflow`). La inferencia conserva su activación explícita
por ejecución. En el servicio, el argumento opcional se llama `meeting_notes`.
Omitir `notas_reunion` o `--meeting-notes` conserva las llamadas existentes.

`consultar_preparacion` devuelve ambas fuentes en el estado persistido; la pausa
`draft_with_chatgpt`, cuando no se inyecta proveedor, también las entrega por
separado. Las citas usan `source_id: "transcript"` o
`source_id: "meeting_notes"`, con una cita literal que debe aparecer en esa fuente.
Una nota por sí sola no permite marcar un hallazgo `confirmed`: esa condición
sigue requiriendo evidencia de la transcripción. No se admiten citas del catálogo
de proyectos ni se incluyen secciones de antecedentes o comparaciones.

Si las fuentes discrepan, el borrador debe conservar ambas citas, marcar el
hallazgo `unknown` y explicar la discrepancia en el resumen y las preguntas
pendientes para revisión. Las instrucciones de redacción se aplican tanto al
proveedor como a la preparación desde el chat; la validación comprueba citas y
procedencia, y el Engagement Manager revisa su interpretación antes de aprobar.

Las notas se guardan en el checkpoint y como `meeting-notes.md` en los artefactos
SQL de cada revisión. Se conservan al editar el paquete o generar el guion.
Cambiar, añadir o retirar notas de una entrada iniciada exige conciliación: se
rechaza reutilizar el checkpoint con otra entrada. Sin notas se conserva la huella
histórica. Reanudar usa las fuentes persistidas, incluidas las notas.

La presentación y el guion mantienen sus aprobaciones separadas. La exportación
aprobada y la entrega al agente 2 conservan el contrato de seis archivos y su
manifiesto; las notas de entrada permanecen consultables en el expediente y sus
artefactos, sin añadir un séptimo archivo al manifiesto.

## Transcripción de Stuart: Nike Lindora

`insumos temporales de agente 1/` está directamente en la raíz y contiene
los cuatro documentos (ficha PDF, resumen PDF y presentación HTML y PDF), junto con
`transcripcion-reunion-nike.md`, la transcripción completa de la reunión. No hay otra
carpeta `insumos/` que los envuelva.

La transcripción original, su versión legible, la revisión del ensayo y el contenido
validado se conservan en `project/backend/fixtures/nike-lindora-stuart/`.
El generador utiliza esos archivos, ejecuta recuperación y preparación en el grafo
local con checkpoints PostgreSQL y se detiene en `awaiting_review`, pendiente de
aprobación. Registra la recepción y la entrega para revisión en la base de workflow;
no llama a modelos externos. Los archivos auxiliares se
producen en un directorio temporal que se elimina; se publican los cuatro documentos y la transcripción completa.

Requiere `WORKFLOW_DATABASE_URL` configurada en el `secrets.env` externo. Cada revisión
vincula primero los cinco archivos de presentación mediante sus hashes; un reintento valida los archivos
existentes sin regenerarlos. Ver [trazabilidad y conciliación](handoffs.md).

La aprobación de presentación genera un guion local por diapositiva, basado en
la misma lista y orden de diapositivas que el exportador HTML/PDF. Se guarda como
`speaker-notes.md` en una nueva revisión, todavía pendiente de aprobación del
gerente. No consume inferencia. Se puede mejorar desde el chat mediante
`actualizar_insumos` con `speaker_notes`; la aprobación final usa el número de
esa nueva revisión. Tras aprobarlo, `exportar_paquete_aprobado` copia los cinco
archivos originales y el guion exacto aprobado a `approved/<case_id>/v<revision>/`
y registra el manifiesto de seis archivos. No altera el paquete de otra revisión.
El agente 2 publica los seis archivos y `manifest.json` para Arquitectura.

La generación inicial registra los cinco archivos antes de la aprobación de
presentación. Desde MCP se puede hacer con `registrar_archivos_presentacion`.
Una vez aprobado también el guion, la exportación está disponible desde la CLI:

```sh
cd project/backend
.venv/bin/python -m app.cli.preparation_documents export --request fixtures/nike-lindora-stuart/opening.json
```

El fixture histórico de cinco archivos solo describe los insumos de presentación.
La CLI de apertura toma el sexto archivo del manifiesto aprobado; nunca lo inventa
ni acepta otra versión del guion. Los expedientes ya persistidos no se actualizan automáticamente.

```sh
PYTHONPATH=project/backend project/backend/.venv/bin/python scripts/generate-stuart-insumos.py
project/backend/.venv/bin/python scripts/build-playbook.py
project/backend/.venv/bin/python scripts/verify-insumos.py --directory 'insumos temporales de agente 1' --qa /private/tmp/stuart-insumos-qa
```

La ficha tiene dos páginas; el resumen, cuatro; la presentación, doce diapositivas.
La vista conjunta está en `docs/design/playbook.html`.

## Generación offline del caso vigente

`make insumos-mock` usa exclusivamente el fixture Nike Lindora de Stuart. No usa
la configuración privada, clientes reales, bases activas, LiveKit ni servicios externos.
Ejecuta el grafo con un proveedor guionado y termina en `awaiting_review`;
no aprueba ni entrega el expediente automáticamente.

```sh
make setup-backend
make insumos-mock
```

La salida local `insumos/` contiene ficha y resumen PDF, presentación HTML y PDF,
transcripción bajo `fuentes/` y un manifiesto de hashes. Es una exportación offline
del mismo caso vigente; el comando persistente anterior conserva la entrega
aprobada en su ubicación original. La demo no sobrescribe ese paquete aprobado.

`make setup-backend` instala Playwright y su Chromium compatible. En Linux mínimo,
instalar también las bibliotecas del sistema con
`project/backend/.venv/bin/python -m playwright install-deps chromium`.
`INSUMOS_BROWSER` permite elegir explícitamente otro Chromium.

## Generador reutilizable

`preparation/insumos.py` valida transcripción, evidencia y contenido preparado.
`integrations/insumos_export.py` adapta ese contenido a ReportLab y HTML.
`demos/insumos.py` compone el proveedor ficticio con el grafo existente.
`cli/insumos.py` ofrece el comando local; no introduce rutas HTTP ni workers.

Para exportar otro contenido preparado explícitamente:

```sh
cd project/backend
.venv/bin/python -m app.cli.insumos \
  --transcript /ruta/transcript.json \
  --content /ruta/contenido-validado.json \
  --output /ruta/insumos
```

Los JSON del fixture sirven como contrato de entrada. `facts` incorpora los datos
visibles de inversión y calendario; `executive`, propósito, recomendación, resultados
esperados y seguimiento; `proposal`, el desarrollo de la consultora. Estos campos
son opcionales para conservar la lectura de preparaciones anteriores. Las
recomendaciones mantienen estado `proposed` y referencias a las necesidades que
las motivan; no se convierten en acuerdos del cliente por tener una cita.

La ficha tiene dos páginas; el resumen, cuatro; la presentación, doce diapositivas.
La audiencia prioritaria es Junta Directiva y vicepresidencias. El propósito del
caso es conocimiento y seguimiento de un encargo definido, no una solicitud
artificial de aprobación.

 La preparación debe declarar
el SHA-256 de la transcripción y referenciar IDs existentes; cada métrica necesita
una cita literal con el mismo valor. El renderizador escapa los textos y no ejecuta
instrucciones de la transcripción. Los PDF y el HTML se publican después de completar
el renderizado de los cuatro documentos. Se conservan los contratos existentes de
`ExecutivePackage`, revisión y handoff; el exportador no aprueba contenido.

La tipografía Lato se incluye localmente con licencia OFL, por lo que abrir los
documentos no requiere Google Fonts ni otra conexión. El HTML mantiene un escenario
16:9, navegación por teclado y gestos, movimiento reducido, impresión y edición local.

## Revisión visual reproducible

Instalar las dependencias de `project/backend/requirements-artifacts-dev.txt` y un
Chromium de Playwright. Después, desde la raíz:

```sh
project/backend/.venv/bin/python scripts/verify-insumos.py \
  --directory insumos --qa /private/tmp/insumos-qa
```

El script renderiza todas las páginas PDF a PNG (Poppler si está disponible; PyMuPDF
como alternativa), abre el HTML con la red desactivada en un navegador aislado y
comprueba dimensiones, desbordamientos, navegación, edición, exportación e impresión.
Captura las doce diapositivas a 1280×720; la revisión se realiza únicamente en escritorio.
Los PNG y el informe quedan en el directorio temporal para inspección visual.
`INSUMOS_BROWSER` permite indicar un ejecutable Chromium de pruebas propio.

## Identidad y vista unificada

Los documentos utilizan la identidad provisional No Name. Los PDF mantienen
fondos blancos, encabezados discretos y tablas sin rellenos. La presentación usa
una base clara con fotografía editorial azul y naranja para la portada del caso
ficticio de maratón; esa imagen no se aplica a proyectos ajenos. Los títulos se
presentan sin punto final y la ficha sustituye al nombre anterior en inglés.

`ficha-proyecto.pdf` es el nombre actual del documento ejecutivo. Los archivos
antiguos generados con otros nombres se conservan y no aparecen en el manifiesto
actual ni en la vista unificada.

Después de `make insumos-mock`, ejecutar:

```sh
project/backend/.venv/bin/python scripts/build-playbook.py
```

Abrir `docs/design/playbook.html` en el navegador integrado de VS Code para revisar
los tres insumos. La ficha y el resumen muestran páginas de los PDF reales, y la
presentación conserva sus controles y animaciones. La vista funciona sin red.
