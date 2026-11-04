# Verificación del correo para el asistente de calendario

El backend consulta la whitelist mediante el contrato de solo lectura
`Whitelist.lookup(email)`. Actualmente `MarkdownWhitelist` lee los registros de
`project/whitelist.md`, privado y excluido de Git. `HTTPWhitelist` permite consultar
un sistema externo; una futura base de datos implementará el mismo contrato.
El agente y las rutas no crean, editan ni habilitan registros. SQLite almacena los
desafíos de verificación, las autorizaciones por llamada y los contadores de uso.

Backend, agente, MCP y comandos OAuth leen una única configuración privada:
`project/.env`. Los correos de la whitelist pertenecen al archivo de registros,
no a las variables de entorno. Las plantillas versionadas son `project/.env.example`
y `project/whitelist.example.md`, sin datos reales.

## Flujo

1. Alisa pide el nombre y el correo, lo deletrea y confirma la transcripción.
2. `iniciar_verificacion_correo` llama a nuestro backend. Este consulta el repositorio
   de whitelist configurado con el correo confirmado.
3. Si no está registrado o habilitado, Alisa indica que debe hablar con un asesor
   de negocio para completar su registro. No se envía ningún código ni se accede
   al calendario. La whitelist no se modifica.
4. Si está habilitado, el backend genera un código y envía el correo transaccional
   HTML con alternativa de texto simple. `code_sent` indica aceptación por Gmail o SMTP;
   no garantiza que haya llegado a la bandeja de entrada.
5. Alisa solicita los seis dígitos y llama a `validar_codigo_correo`. El backend
   verifica el desafío y vuelve a consultar si el registro sigue habilitado.
6. Solo `verified` autoriza el acceso. Cada herramienta de calendario llama al
   backend para comprobar la sesión, el correo y el registro nuevamente.
7. Cambiar el correo exige una nueva verificación. Una llamada nueva tiene una
   identidad nueva y requiere su propio código.

La llamada debe poder iniciarse para recoger el correo. Si se quiere impedir la
conexión de usuarios no registrados desde el principio, la verificación debe
realizarse en el portal previo a la llamada.

## Integración con LiveKit

El agente ya utiliza `MCPToolset` y un servidor MCP local lanzado con
`MCPServerStdio`. Las tres herramientas de verificación se agregan a ese servidor;
este llama por HTTP a nuestro backend. El backend consulta el repositorio de
whitelist; el agente no necesita conocer su almacenamiento.

Cada instancia local del servidor MCP genera un identificador aleatorio de
llamada. El modelo no puede proporcionar ese identificador, el desafío ni las
credenciales. Solo recibe estados y datos de reintento. Este aislamiento depende
de mantener un proceso MCP por llamada, como hace la configuración actual; un
servidor MCP compartido requeriría contexto autenticado por sesión.

LiveKit también admite herramientas `@function_tool` que llaman APIs directamente.
Se mantiene MCP para integrar los permisos en las herramientas de calendario
existentes. Documentación consultada:

- [Function tools y llamadas HTTP](https://docs.livekit.io/agents/logic/tools/definition/).
- [MCPToolset y servidores locales](https://docs.livekit.io/agents/logic/tools/mcp/).
- [Depurador del agente](https://docs.livekit.io/testing/debugger/).

## Almacenamiento local y migración

`CALENDAR_WHITELIST_PROVIDER=file` selecciona `MarkdownWhitelist`.
`CALENDAR_WHITELIST_FILE=whitelist.md` se resuelve respecto a `project/`.
Copiar la plantilla vacía y añadir filas con `email`, `name` y `enabled`
(`true` o `false`), manteniendo la cabecera y el separador de la tabla.
Cada consulta vuelve a leer y validar todos los registros. Los duplicados,
registros inválidos o errores de archivo producen `unavailable`; una tabla vacía
no permite ningún contacto. No existe fallback hacia correos en `.env`.

Para migrar a una BD, implementar `Whitelist.lookup` y registrar el adaptador en
`configured_whitelist()` dentro de `app/services/calendar_whitelist.py`.
Los registros mantienen correo único, nombre y estado habilitado. Las comprobaciones
de acceso y el flujo de códigos permanecen independientes del almacenamiento.

## Contrato propuesto de la whitelist externa

Seleccionar `CALENDAR_WHITELIST_PROVIDER=http` y configurar `CALENDAR_WHITELIST_URL` con la URL completa y
`CALENDAR_WHITELIST_API_KEY` con su credencial. El adaptador está en
`../app/services/calendar_whitelist.py`; se ajusta ahí cuando el otro sistema
confirme su contrato real.

Solicitud: `POST` autenticado con `Authorization: Bearer <credencial externa>`.
El método se usa como consulta y no modifica el registro.

```json
{"email":"cliente@example.com"}
```

Respuesta de un correo registrado, HTTP 200:

```json
{"registered":true,"enabled":true,"name":"Nombre registrado"}
```

Respuesta de un correo no registrado, HTTP 200:

```json
{"registered":false}
```

Se requiere HTTPS, salvo localhost para desarrollo. La consulta tiene un timeout
de cinco segundos y no sigue redirecciones. Errores HTTP, respuestas mal formadas
y fallas de red se consideran `unavailable`, nunca «no registrado».

## API de nuestro backend

Todas las rutas usan el prefijo `/api/calendar-access` y requieren
`Authorization: Bearer <CALENDAR_ACCESS_SERVICE_KEY>`. Esta clave solo se comparte
entre el servidor del agente y el backend, nunca con el navegador ni el modelo.

| Ruta POST | Entrada | Resultado principal |
| --- | --- | --- |
| `/start` | `session_id`, `email`, `origin_id` | `code_sent`, desafío y vencimiento; o `not_registered`, `not_enabled`, `rate_limited`, `unavailable` |
| `/verify` | `session_id`, `challenge_id`, `code` como string | `verified`; o `invalid_code`, `expired`, `attempts_exceeded`, `verification_required`, `unavailable` |
| `/resend` | `session_id`, `challenge_id` | `code_sent` con desafío nuevo; o espera/rechazo |
| `/authorize` | `session_id`, `email`, `operation` | `authorized`; o rechazo de acceso |
| `/close` | `session_id` | `closed`; invalida código y autorización |

`operation` admite `availability`, `search`, `book`, `reschedule` y `cancel`.
Un estado de rechazo nunca permite ejecutar la operación. Las respuestas de negocio
usan HTTP 200 con `status`; las credenciales inválidas usan 401 y la configuración
incompleta usa 503. Las fallas de red también deben impedir el acceso.

## Reglas implementadas

- Código aleatorio de seis dígitos, incluidos ceros iniciales, válido cinco minutos
  y de un solo uso. Se persiste únicamente un HMAC ligado a sesión, correo y
  desafío; el secreto HMAC es independiente de la clave de servicio.
- Cinco intentos por desafío y diez fallos por correo u origen en quince minutos.
  Reenviar o crear otra llamada no reinicia el límite acumulado.
- Espera de sesenta segundos entre envíos para un correo o llamada; máximo cinco
  envíos por correo y diez por origen en una hora. Las solicitudes fallidas de
  envío también consumen cuota para evitar reintentos ilimitados.
- Un reenvío invalida el código anterior. Una autorización dura como máximo treinta
  minutos; cerrar la llamada la revoca. El cierre al terminar el proceso es de
  mejor esfuerzo; el vencimiento limita las sesiones que terminen abruptamente.
- El origen lo configura el servicio confiable, no el modelo. El valor por defecto
  comparte un límite entre llamadas del servicio. Para límites por llamante, el
  servicio de entrada debe aportar una identidad estable y confiable.
- SQLite conserva autorizaciones y límites tras reinicios; las transacciones
  serializan cambios y consumo de códigos. Los eventos de uso anteriores a un día
  se purgan al solicitar un código. Las filas de sesión se conservan; su retención
  y almacenamiento persistente se deben definir al desplegar.
- Una caída de la whitelist o del backend bloquea el acceso. Cuando se detecta un
  registro deshabilitado, se revoca la autorización; habilitarlo de nuevo exige
  otra verificación.

## Configuración y verificación

Consultar [el README del backend](../app/README.md) para iniciarlo, autorizar Gmail o configurar SMTP
y ejecutar sus pruebas. En el único `project/.env` se necesita:

```dotenv
CALENDAR_ACCESS_URL=http://127.0.0.1:8000/api/calendar-access
CALENDAR_ACCESS_SERVICE_KEY=<misma clave que en el backend>
CALENDAR_ACCESS_ORIGIN_ID=calendar-assistant
```

Las credenciales de la whitelist y del proveedor de correo permanecen en el backend.
Gmail usa un token separado en `project/secrets/gmail_token.json`, con permiso de
envío `gmail.send`; no utiliza el token de Calendar ni requiere leer el buzón.
Nunca se devuelve el código generado al agente ni se registra explícitamente en
nuestros logs. Al dictarlo, el código pasa por STT, el modelo y la herramienta:
las transcripciones, trazas y grabaciones de LiveKit requieren una política de
redacción y retención antes de usar el flujo con datos reales.
