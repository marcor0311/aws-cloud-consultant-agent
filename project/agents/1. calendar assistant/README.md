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

Las reuniones duran treinta minutos, de lunes a viernes, hora de Costa Rica.
Pueden iniciar a los minutos 00 o 30, entre 08:00 y 11:30 y entre 13:00 y 16:30.
Los rangos ofrecidos representan horas de inicio. Las herramientas vuelven a
validar la autorización y las reglas al agendar o reagendar.

Reagendar y cancelar requieren identificar la cita del correo aprobado y una
confirmación explícita de la persona. El servidor comprueba que el evento siga
vigente y que no haya cambiado. La despedida termina con `end_call` y espera
la reproducción del mensaje antes de cerrar.

La preparación ejecutiva del primer issue es una responsabilidad pendiente de
otro agente; Calendar Assistant se limita al agendamiento.

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

La suite conserva una conexión real al servidor MCP con invocación de herramienta.
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
