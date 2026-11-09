# Identificación de cliente y verificación OTP

## Flujo de voz

1. Alisa solicita el nombre y pide indicar el código de cliente usando el
   alfabeto fonético internacional, sin ejemplos ni pistas del formato.
2. `preparar_confirmacion_cliente` normaliza letras, palabras fonéticas y números
   en español. Separa los grupos al repetir el código y conserva ceros y repeticiones.
   Ejemplo: `IOAA-0012`: “Letras: India, Oscar, Alfa, Alfa. Números: cero, cero, uno, dos”.
3. Después de confirmar, `iniciar_verificacion_cliente` envía el código al backend.
   Este localiza la empresa por `client_code`; no acepta un correo del llamante.
4. Si el cliente está habilitado, envía un OTP de seis dígitos solo a `company_email`.
   Las herramientas no revelan el correo aprobado, ni completo ni parcialmente.
   Si no está registrado o habilitado, remite al asesor de negocio.
5. `validar_codigo_correo` valida el OTP. El código de cliente por sí solo no permite
   ninguna consulta o gestión de calendario. Un cambio de cliente exige otro OTP.
6. Las herramientas de Calendar omiten `correo_confirmado` y usan la dirección
   verificada guardada en el proceso MCP. El correo no se devuelve al modelo.
   Cambios al registro corresponden al área de negocio, fuera de la llamada.

Alfabeto: Alfa, Bravo, Charlie, Delta, Echo, Foxtrot, Golf, Hotel, India, Juliett,
Kilo, Lima, Mike, November, Oscar, Papa, Quebec, Romeo, Sierra, Tango, Uniform,
Victor, Whiskey, X-ray, Yankee, Zulu. I y O están permitidas; Ñ está excluida.

## Persistencia y registro

La tabla `clients` usa `client_id INTEGER PRIMARY KEY AUTOINCREMENT`, `client_code`
único, `company_name`, `company_email` único y `enabled`. Los códigos se generan
solo en el servidor con `secrets`, comprobación de existencia y reintento ante
colisión. UNIQUE y transacciones serializan el registro concurrente.

Negocio pre-registra mediante `python -m app.cli.clients add`; consultar
[la configuración del backend](../../backend/README.md). No existe herramienta del
modelo para crear empresas, habilitarlas o modificar sus correos.

Se revalida el registro antes de enviar, reenviar, verificar y autorizar cada
operación. Si el correo aprobado cambió, no se reutiliza un OTP enviado al anterior
ni se reenvía a la nueva dirección dentro de esa verificación. Se exige comenzar
otra vez con el código de cliente. Un registro eliminado o deshabilitado revoca
la autorización al detectarse. Una falla de almacenamiento produce `unavailable`.

Las sesiones existentes sin código de cliente se invalidan al migrar el esquema.
Los eventos de límites de uso se conservan. El registro vigente de empresas
es la tabla `clients` en SQLite, administrada mediante el comando del backend.

## API interna

Prefijo `/api/calendar-access`, siempre con
`Authorization: Bearer <CALENDAR_ACCESS_SERVICE_KEY>`.

| Ruta POST | Entrada | Resultado principal |
| --- | --- | --- |
| `/start` | `session_id`, `client_code`, `origin_id` | `code_sent`, desafío, vigencia; sin correo ni OTP |
| `/verify` | `session_id`, `challenge_id`, `code` de seis dígitos como string | `verified`; dirección solo para el cliente MCP confiable |
| `/resend` | `session_id`, `challenge_id` | `code_sent` con nuevo desafío |
| `/authorize` | `session_id`, `email`, `operation` | `authorized`; o rechazo |
| `/close` | `session_id` | `closed`; revoca OTP y autorización |

`operation`: `availability`, `search`, `book`, `reschedule`, `cancel`.
No se acepta `email` en `/start`; los campos extra se rechazan. El proceso MCP
recibe el correo únicamente al verificar el OTP y lo conserva fuera del contexto
del modelo. Los resultados de agenda tampoco incluyen el correo del invitado.
Cada llamada crea un proceso MCP y una identidad de sesión distintos; el modelo
no elige el ID de sesión, desafío, origen o credenciales.

## Límites conservados

- OTP criptográfico de seis dígitos, cinco minutos, uso único; solo se persiste
  su HMAC ligado a sesión, correo y desafío. No se devuelve ni se registra el OTP.
- Cinco intentos por desafío y diez fallos por correo u origen en quince minutos.
- Sesenta segundos entre envíos por correo o llamada; cinco envíos por correo
  y diez por origen en una hora. Un intento de envío fallido consume cuota.
- Reenviar invalida el OTP anterior. La autorización vence a los treinta minutos.
  Cerrar revoca el acceso; el cierre de proceso es de mejor esfuerzo.
- Límites y sesiones sobreviven reinicios. Eventos anteriores a un día se purgan
  al emitir códigos. Los límites por origen dependen de una identidad confiable;
  el origen predeterminado comparte cuota entre llamadas del servicio.
- Los errores de backend bloquean el calendario. Ningún fallo permite acceso.

El dictado del OTP atraviesa STT y el modelo; la configuración de retención de
transcripciones y trazas de LiveKit también debe proteger esos datos.

Referencias: [MCPToolset](https://docs.livekit.io/agents/logic/tools/mcp/),
[simulaciones](https://docs.livekit.io/testing/simulations/) y
[depurador](https://docs.livekit.io/testing/debugger/).
