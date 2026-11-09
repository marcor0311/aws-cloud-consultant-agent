# Registro al cierre y webhook de Calendar

## Flujo implementado

1. La herramienta verifica al cliente por OTP y crea la cita en Google. Conserva
   una única referencia privada en `project/data/post-call/*.active`. Si cambia
   durante la conversación, reemplaza el resultado anterior. No envía el handoff
   ni llama otro modelo durante la conversación.
2. El shutdown hook espera el cierre de la sesión de audio. Luego firma el recibo,
   lo marca listo y lo entrega a `POST /api/calendar-access/call-ended`, con un
   timeout de cuatro segundos. El modelo no participa.
3. El backend valida la firma, el cliente habilitado y el resultado único por
   llamada. Guarda la reunión vinculada al cliente y una tarea persistida. No
   consulta Google ni genera insumos dentro de esa petición.
4. El worker recupera la cita, comprueba sus metadatos y participante, y deja el
   expediente de LangGraph en `awaiting_meeting`. Si HTTP falló al cerrar, recupera
   el recibo firmado desde la misma carpeta local. Los reintentos no duplican la
   reunión. La sesión OTP sigue revocándose al terminar la conversación.

Los archivos `.active` de un proceso terminado abruptamente se conservan para
inspección; no se procesan como si la llamada hubiese terminado normalmente.
La recuperación por carpeta corresponde al modo local con almacenamiento
compartido del repositorio; no funciona entre máquinas independientes.

El webhook vigila el calendario, pero solo procesa citas ya vinculadas a un
expediente. Un aviso temprano nunca inicia el proyecto mientras el cliente sigue
conversando. Al registrar la referencia final, el worker consulta el estado actual.
Cancelación y cambio de horario se distinguen; rechazar una invitación no cancela
automáticamente el expediente.

## Configuración local de esta fase

En `project/.env` (las rutas OAuth relativas usan el directorio privado externo):

```dotenv
WORKFLOW_ENABLED=1
WORKFLOW_MODE=live
# Esta fase usa Calendar. Meet requerirá su autorización adicional después.
WORKFLOW_GOOGLE_TOKEN_FILE=google/calendar-token.json
WORKFLOW_CALENDAR_WEBHOOK_URL=
```

Se reutiliza el cliente OAuth de Calendar y el scope `calendar.events.owned`.
No hay que crear una API distinta ni configurar Pub/Sub para este webhook.
El proveedor de IA, Slack y Meet no son necesarios para registrar y seguir citas.
La inferencia de voz sigue requiriendo autorización explícita por ejecución.

Abrir dos terminales desde la raíz:

```sh
make backend
```

```sh
make workflow
```

Para consultar únicamente lo persistido, sin llamar a Google:

```sh
make meetings
```

## Activar el webhook real

Google necesita una URL HTTPS accesible; no puede enviar notificaciones a
`localhost`. El receptor exclusivo reutiliza el mismo handler y la misma BD, pero
solo expone `POST /api/workflow/events/calendar`, sin rutas privadas ni documentación.
Iniciarlo en otra terminal:

```sh
make calendar-webhook
```

Para desarrollo se puede instalar `cloudflared` desde su fuente oficial y ejecutar,
tras autorizar la exposición de ese receptor:

```sh
cloudflared tunnel --url http://127.0.0.1:8001
```

El túnel hace accesible únicamente ese receptor por una URL temporal; otras rutas
devuelven `404` y otros métodos en el callback devuelven `405`. El webhook valida
token, canal y recurso. No se debe compartir la clave del servicio ni incluirla
en la URL. El backend privado del puerto 8000 no se publica.

Copiar la URL HTTPS que imprime el túnel y añadirle la ruta:

```dotenv
WORKFLOW_CALENDAR_WEBHOOK_URL=https://URL-DEL-TUNEL/api/workflow/events/calendar
```

Reiniciar backend, receptor y worker después de cambiar `.env` y ejecutar:

```sh
make calendar-watch
```

Este comando registra el canal en Google; no genera llamadas de voz ni inferencia.
El worker también comprueba su vencimiento y crea un canal de reemplazo antes de
expirar. Un túnel nuevo requiere actualizar la URL y registrar el nuevo canal.

Google envía cabeceras, sin el evento completo. La petición HTTP solo persiste la
notificación; el worker recupera cambios con `syncToken`, procesa páginas y
reinicia la sincronización si Google devuelve `410`. No combina `syncToken` con
filtros privados incompatibles. Los eventos ajenos se descartan localmente y las
eliminaciones se vinculan por calendario/ID, aunque no traigan metadatos.

No se consulta el calendario cada minuto. Hay sincronización al activar/renovar
el canal, al iniciar el worker con webhook configurado y al recibir avisos.
Como Google no garantiza todos los avisos, se ofrece recuperación bajo demanda:

```sh
make calendar-sync
```

El webhook no prueba que se celebró una reunión. Para cuentas sin transcripción
nativa, la [captura local de subtítulos](../project/transcript-capture/README.md)
entrega nombre, texto y tiempos al backend privado. Salir desde el navegador
finaliza esa captura; no demuestra que todos los participantes abandonaron Meet.
La validación real de extremo a extremo requiere el túnel activo y una cita
controlada. Las pruebas automáticas usan transporte ficticio, SQL y grafos reales.

Referencias: [Calendar push](https://developers.google.com/workspace/calendar/api/guides/push),
[events.watch](https://developers.google.com/workspace/calendar/api/v3/reference/events/watch),
[sincronización incremental](https://developers.google.com/workspace/calendar/api/guides/sync),
[shutdown hooks LiveKit](https://docs.livekit.io/agents/server/job/),
[Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).
