# Agente 1 — Calendar Assistant

Calendar Assistant es el agente de agendamiento del Engagement Manager definido
en el [primer issue](../../../issues.md). La asistente de voz se presenta como
Alisa y gestiona reuniones con Stuart. Su identificador sigue siendo
`calendar_assistant`.

El registro del conjunto de agentes y los límites con la API están en
[agents/README.md](../README.md).

## Organización del agente

| Archivo o carpeta | Responsabilidad |
| --- | --- |
| `agent.json` | Número, nombre, identificador, etapa y configuración de LLM, STT y TTS |
| `prompts/assistant.txt` | Instrucciones que `src/agent.py` carga al crear la asistente |
| `src/agent.py` | Sesión de voz, carga de modelos, herramientas y cierre de llamada |
| `src/tools/calendar_mcp.py` | Herramientas de Calendar, disponibilidad y reglas de reuniones |
| `src/integrations/access_client.py` | Comunicación HTTP con la verificación y autorización del backend |
| `src/tools/advisor_transfer.py` | Fase de derivación sin calendario y aceptación posterior a la oferta |
| `src/integrations/sip_transfer.py` | SIP REFER sobre el participante SIP de la llamada activa |
| `src/domain/client_codes.py` | Normalización y confirmación fonética del código de cliente |
| `src/domain/scheduling.py` | Reglas de reuniones, interpretación de fechas y rangos de inicio |
| `src/integrations/google_calendar.py` | Cliente y credenciales de Google Calendar |
| `src/config.py` | Lectura de las variables permitidas de `project/.env` |
| `src/integrations/google_oauth.py` | Autorización local de Google Calendar |
| `tests/` | Pruebas del agente, sus herramientas y configuración |
| `pyproject.toml`, `uv.lock` | Dependencias y versiones reproducibles del paquete `calendar-assistant` |

Las instrucciones, los modelos y las pruebas locales son archivos
versionados. El agente carga la identidad de `agent.json` y la incluye en sus
campos de log.

## Configuración local

`project/.env` contiene configuración no sensible y la ruta
`CLOUD_CONSULTANT_SECRETS_DIR`. El directorio privado predeterminado es
`~/.config/aws-cloud-consultant-agent/dev/`. El agente solo incorpora sus variables
desde `secrets.env`; las credenciales exclusivas del backend no entran en su entorno.
Las variables del proceso tienen prioridad.

Las rutas OAuth relativas se resuelven desde ese directorio privado: por defecto,
`google/oauth-client.json` y `google/calendar-token.json`. Gmail utiliza el mismo
cliente, pero conserva su token separado en `google/gmail-token.json`.
Ver [estructura de ejemplo y migración](../../../config/local-secrets.example/README.md).

Desde la raíz del repositorio, para ejecutar el agente localmente:

La inferencia real está bloqueada por defecto. Solo tras autorizar el consumo de
créditos, añade `LIVEKIT_INFERENCE_ENABLED=1` al comando de una prueba concreta
(por ejemplo, `LIVEKIT_INFERENCE_ENABLED=1 make agent`). No lo dejes activado
permanentemente en `project/.env`. Las pruebas locales no necesitan esta variable.
No hay simulaciones cloud ni llamadas reales automatizadas en las pruebas o CI.

```sh
cd "project/agents/1. calendar assistant"
uv sync --locked
lk agent console
```

Desde la raíz se puede iniciar cada componente en su terminal:

```sh
make backend
```

```sh
make agent
```

La configuración del agente debe apuntar al mismo puerto mediante
`CALENDAR_ACCESS_URL=http://127.0.0.1:8000/api/calendar-access`.

## Comportamiento actual

Alisa solicita el código de cliente usando el alfabeto fonético internacional,
sin dar ejemplos ni pistas del formato. Confirma el código dictado y solicita
un OTP que el backend envía exclusivamente al correo aprobado de la empresa.
El código de cliente identifica el registro; solo el OTP autoriza gestionar citas.
No se revela ni se cambia el correo aprobado durante la conversación.

Si el backend devuelve `not_registered` o `not_enabled`, incluso al revalidar una
operación de agenda, Alisa pasa a una fase sin herramientas de calendario y ofrece
comunicar con un asesor de negocio. Solo una aceptación explícita en un mensaje
posterior a la oferta permite intentar la transferencia. Si rechaza, termina la
gestión y explica cómo contactar a Stuart. La autorización OTP no se sustituye
por la transferencia ni por la aceptación de la oferta.

### Transferencia de la llamada activa

Configura `CALENDAR_ADVISOR_TRANSFER_E164` únicamente en el `secrets.env` privado
o en el entorno del proceso, con `+` seguido del número internacional E.164. No se
carga el destino desde `project/.env`, no se acepta como argumento del modelo y
no se incluye en prompts, respuestas ni logs. El ejemplo versionado permanece vacío.
Si falta o es inválido, Alisa explica la alternativa de contacto sin enviar REFER.

`CALENDAR_ADVISOR_TRANSFER_TIMEOUT_SECONDS` fija la espera de respuesta (entero de
1 a 120, predeterminado 10 segundos); puede ir en la configuración no sensible.
El request lleva `ringing_timeout` y un timeout HTTP cinco segundos mayor, con un
límite local adicional. Alisa espera el resultado y, ante falta de respuesta,
rechazo o error de transporte, retoma la conversación y orienta a contactar a
Stuart en el correo habitual. No reintenta automáticamente: un timeout de red
puede dejar incierto el resultado remoto. Solo la respuesta de LiveKit con estado
exitoso confirma la transferencia; entonces se cierra la sesión del agente sin
eliminar la sala ni colgar al destinatario.

Se requiere una llamada SIP ya contestada y un único participante SIP remoto en
la sala. Las sesiones web o de consola y las salas con varios participantes SIP
no se transfieren. El proveedor debe soportar SIP REFER a destinos `tel:` y
notificar su resultado. Algunos proveedores exigen un URI SIP específico; ese
caso requiere adaptar la integración antes de una prueba autorizada.

La recuperación de audio depende del proveedor. LiveKit documenta un timeout de
medios de 15 segundos por defecto: si se configura una espera de timbrado mayor,
el `media_timeout` de la llamada debe superar esa espera. No se modifican trunks
ni cuentas desde este proyecto. Un buzón o IVR que conteste cuenta como éxito
para el proveedor y no demuestra que respondió una persona.
Ver [SIP REFER, timeout y fallos](https://docs.livekit.io/telephony/features/transfers/cold/).
La prueba telefónica y la comprensión con un modelo real requieren autorización
explícita para cada ejecución; esta implementación se valida con mocks offline.

Las reuniones duran treinta minutos, de lunes a viernes, hora de Costa Rica.
Pueden iniciar a los minutos 00 o 30, entre 08:00 y 11:30 y entre 13:00 y 16:30.
Los rangos ofrecidos representan horas de inicio. Las herramientas vuelven a
validar la autorización y las reglas al agendar o reagendar.

Reagendar y cancelar requieren identificar la cita del correo aprobado y una
confirmación explícita de la persona. El servidor comprueba que el evento siga
vigente y que no haya cambiado. La despedida termina con `end_call` y espera
la reproducción del mensaje antes de cerrar.

La preparación ejecutiva del primer issue tiene un runtime separado en
`backend/app/preparation/`. Recibe transcripción, notas de reunión opcionales y
consulta de antecedentes desde MCP o CLI; ver [entradas y revisión](../../../docs/insumos.md#preparación-con-notas-de-reunión).
Calendar Assistant conserva su responsabilidad de agendamiento.

En una llamada real, la cita se conserva como una sola referencia local. Después
del cierre del audio se entrega al backend mediante un recibo firmado; el worker
la registra y espera la reunión. El procesamiento y los webhooks no usan el modelo
de voz. Ver [registro al cierre y webhook de Calendar](../../../docs/calendar-integration.md).

## Validación local

Desde esta carpeta:

```sh
uv run --locked pytest -q
uv run --locked ruff format --check src tests demos
uv run --locked ruff check src tests demos
```

La suite conserva una conexión real al servidor MCP con invocación de herramienta,
extendida al SDK y backend HTTP local simulado para la derivación: rechazo de la
oferta, aceptación, timeout, rechazo del proveedor y transferencia completada.
Los mensajes son guionados: verifican herramientas y efectos, no comprensión del lenguaje.
El recorrido de agenda y cierre con recibo queda en el E2E bajo demanda.
Las pruebas locales utilizan datos, transcripts y proveedores ficticios. Los
modelos guionados no consumen créditos de inferencia. CI ejecuta estas pruebas
locales y no inicia llamadas reales ni simulaciones cloud.
El recorrido completo se activa bajo demanda con `make test-e2e`.

Consultar [la configuración del backend](../../backend/README.md) y
[el flujo de verificación](VERIFICACION_CORREO.md) para los contratos y límites.

Para autorizar Calendar desde la raíz del repositorio: `make calendar-auth`.
El servidor MCP se inicia como `python -m src.tools.calendar_mcp` desde esta
carpeta. Las integraciones resuelven las rutas privadas desde la carpeta del
agente; no dependen del directorio de sus módulos internos.


## Demostración local

`demos/voice.py` contiene el runner guionado con proveedores ficticios. El backend
lo invoca con `python -m demos.voice` durante `make test-demo`, conservando
`src/agent.py` como entrada de producción. Los mocks ejecutables siguen en
`src/integrations/`. La demo no modifica prompts ni modelos de voz.
