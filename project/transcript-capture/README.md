# Captura de Meet para desarrollo local

Adaptación de [TranscripTonic](https://github.com/vivek-nexus/transcriptonic), MIT,
fijada al commit `1e38252610b2d6ab2347e3a15a5d1d1da325505c`. Se reutilizan sus
observadores de subtítulos y su manejo de revisiones de texto. `prepare.py`
comprueba el SHA-256 del archivo original y conserva la licencia en la extensión.
El transporte, almacenamiento de entregas y popup son locales de este proyecto.

## Preparar y cargar

Desde la raíz, con las dependencias del backend instaladas:

```sh
make prepare-capture
make backend
```

La primera preparación descarga la versión fijada; las siguientes usan una copia
verificada en `project/generated/`. También admite `prepare.py --archive ARCHIVO`.
El comando reutiliza `WORKFLOW_TRANSCRIPT_TOKEN` del proceso o del `secrets.env`
externo seleccionado por `CLOUD_CONSULTANT_SECRETS_DIR`. Solo genera y guarda un
token allí cuando no existe; no escribe credenciales nuevas en `project/.env`.
Al cambiar esa configuración hay que reiniciar el backend. No modifica los tokens
de Google ni las credenciales del agente de voz.

1. Abrir `chrome://extensions` en el Chrome donde Stuart participará.
2. Activar **Modo de desarrollador** y pulsar **Cargar descomprimida**.
3. Seleccionar `project/generated/transcriptonic` y fijar su icono.
4. Abrir una sola reunión usando su enlace `https://meet.google.com/xxx-xxxx-xxx`
   o `https://meet.google.com/meet/xxx-xxxx-xxx`. También se detecta la entrada
   desde la pantalla de inicio de Meet sin recargar la página.
   Evitar recargar esa pestaña: la reserva impide sobrescribir una captura activa.
5. Comprobar los subtítulos y seleccionar español en Meet. La extensión intenta
   activarlos, pero la captura real debe comprobarse en pantalla y en su popup.
6. Salir mediante el botón de colgar de Meet. La extensión entrega el transcript
   al backend de esta computadora, en `http://127.0.0.1:8000`.

Después de reconstruir una extensión ya instalada, pulsar **Recargar** en su
tarjeta de `chrome://extensions` y comprobar la versión **v1.0.1** en el popup.
Luego recargar la pestaña de Meet antes de entrar a una nueva llamada. Recargar
solo la página no actualiza el código que Chrome ya tenía cargado de la extensión.
Hacer estos pasos cuando no haya una captura activa. Si cambió el código del
backend, reiniciar también `make backend` para que use el validador actualizado.

El popup se actualiza mientras permanece abierto: **Meet abierto** confirma la
activación; el contador muestra intervenciones ya guardadas y aumenta al finalizar
un bloque de habla. La intervención que aún está en curso se vacía al colgar.

La carpeta generada contiene una credencial privada y está ignorada por Git.
No distribuirla ni cargar simultáneamente la extensión original: esta adaptación
ya incorpora el capturador. El backend debe ejecutarse en la misma computadora.
La extensión solo pide acceso de captura a Meet y acceso de red al backend local;
no publica un nuevo endpoint por Cloudflare ni usa servicios de transcripción,
modelos externos o telemetría de TranscripTonic. Los subtítulos los genera Meet:
guardar su texto localmente no convierte su reconocimiento de voz en local.

## Entrega y progreso

Se guardan nombre mostrado por Meet, texto y momento de cada intervención. No se
capturan mensajes del chat. Los nombres mostrados no son identidades verificadas.
El backend correlaciona código de Meet y comienzo de captura con una única cita
registrada, dentro de una hora antes/después de su horario. No busca por título.
Hay que usar una cita registrada por nuestro flujo y realizar la prueba cerca
de su horario; una reunión creada a mano sin expediente no iniciará preparación.

El endpoint autenticado `POST /api/workflow/events/transcript` solo valida y encola.
El worker conserva el transcript en `workflow_records`, registra su disponibilidad
y avanza el proceso a `preparing`. Si el proveedor de preparación aún no está
configurado, registra `preparation.configuration_required` sin invocar IA.
Si está configurado, encola un comando separado de preparación. No cambia los
entregables ni sus reglas de aprobación.

El popup distingue **Recibida por el backend** de una captura todavía pendiente;
la recepción HTTP no demuestra que el worker haya terminado. El estado del job se
conserva en `workflow_jobs`. El mismo ID con otro contenido se rechaza; un segundo
transcript diferente para el mismo expediente requiere conciliación y no lo pisa.

Si el backend no responde, la captura queda en `chrome.storage.local` y se reintenta
cada minuto o con el botón del popup. Hay copia JSON descargable. No borrar los
datos ni desinstalar la extensión mientras existan pendientes. Cerrar la pestaña
abruptamente conserva una captura **incompleta**, sin publicarla automáticamente.
Salir de Meet finaliza la captura de Stuart; no prueba que todos los demás salieron.

## Verificación

Para comprobar únicamente captura y recepción, se puede usar una reunión
instantánea sin cita registrada, sin LiveKit y sin iniciar el worker. Activar los
subtítulos en español, hablar unos segundos y colgar con el botón de Meet. El
popup debe pasar de **Meet abierto** a **Recibida por el backend**; esto confirma
la aceptación HTTP 202 y la persistencia del payload como `captured_transcript`
en `workflow_jobs`. La copia JSON sigue disponible en la extensión.

Para asociar después una captura a un expediente y avanzar a preparación, usar
una cita registrada dentro de la ventana de correlación indicada arriba y ejecutar
`make workflow` con la configuración correspondiente. La recepción de una reunión
instantánea por sí sola no crea una cita ni un expediente.

El recorrido conservado se ejecuta con
`make test-backend TESTS=tests/workflow/test_transcript_capture.py`.
Comprueba HTTP, SQL, cola y LangGraph con una transcripción simulada.
No se ejecutan llamadas de LiveKit. Ver [suite mínima](../../docs/testing.md).
La comprobación final de selectores, idioma y recepción requiere una reunión humana.
