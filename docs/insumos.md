# Generación local de insumos de reunión

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
vincula los cinco archivos mediante sus hashes; un reintento valida los archivos
existentes sin regenerarlos. Ver [trazabilidad y conciliación](handoffs.md).

```sh
PYTHONPATH=project/backend project/backend/.venv/bin/python scripts/generate-stuart-insumos.py
project/backend/.venv/bin/python scripts/build-playbook.py
project/backend/.venv/bin/python scripts/verify-insumos.py --directory 'insumos temporales de agente 1' --qa /private/tmp/stuart-insumos-qa
```

La ficha tiene dos páginas; el resumen, cuatro; la presentación, doce diapositivas.
La vista conjunta está en `docs/design/playbook.html`. Las instrucciones siguientes
de `make insumos-mock` corresponden al fixture anterior y generan ese otro escenario
en `insumos/`.

`make setup-backend` instala Playwright y su Chromium compatible; la exportación
no depende de tener Chrome instalado en el equipo. En Linux mínimo, instalar
también las bibliotecas del sistema con `project/backend/.venv/bin/python -m
playwright install-deps chromium` (puede requerir permisos de administrador).
`INSUMOS_BROWSER` permite elegir explícitamente otro Chromium.

## Fixture original

Desde la raíz, instalar el backend y el Chromium compatible antes de generar:

```sh
make setup-backend
make insumos-mock
```

`insumos/` contiene dos PDF (resumen de reunión y ficha del proyecto) generados con ReportLab, una presentación HTML autónoma y su versión PDF,
la transcripción ficticia bajo `fuentes/` y un manifiesto con hashes. La salida está
ignorada por Git; los fixtures y el generador sí viven en el código del backend.

La demo ejecuta el grafo existente de preparación con `InMemorySaver`, búsqueda
vacía y un proveedor guionado. Termina en `awaiting_review`; no simula una aprobación
humana ni entrega el proyecto a la etapa siguiente. No usa la configuración privada,
clientes reales, bases activas, LiveKit ni servicios externos.

## Caso de demostración

`project/backend/fixtures/nike-maraton-cr/` contiene una reunión ficticia de
encuadre ejecutivo, con 22 intervenciones. Por autorización del usuario, se refinó
el escenario para representar un encargo completo al llegar a Stuart: alcance,
inversión máxima de USD 24.000, publicación el 18 de enero de 2027 y responsables
definidos. Estos datos son decisiones de construcción del caso ficticio, no
compromisos ni aprobaciones reales de Nike.

Las previsiones son 10.000 usuarios durante el día de campaña y 500 diarios
posteriores. Los 1.500 son sesiones por semana de una campaña anterior; el escenario
aclara su unidad y período. La concurrencia de validación, de 1.000 personas durante
quince minutos, se declara por separado en la reunión; no se calcula desde usuarios
diarios. No se ejecutan pruebas de carga como parte de esta demo.

La demo valida el flujo y los formatos con datos guionados; no evalúa comprensión
de lenguaje por un modelo real.

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

La ficha tiene dos páginas; el resumen, tres; la presentación, diez diapositivas.
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
Captura las diez diapositivas a 1280×720; la revisión se realiza únicamente en escritorio.
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
