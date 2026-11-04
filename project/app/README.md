# Backend de la consultora

FastAPI conserva las rutas de agentes existentes y agrega verificación por correo
para Calendar Assistant. El backend consulta una whitelist mediante un repositorio
de solo lectura; hoy usa un Markdown privado y permite cambiar el almacenamiento
sin modificar la verificación. Genera códigos, envía correos y autoriza cada llamada.

## Ejecutar

Desde `project/`, con Python 3.10 o posterior:

```sh
python3 -m venv .venv-backend
source .venv-backend/bin/activate
python -m pip install -r app/requirements.txt
cp .env.example .env
cp whitelist.example.md whitelist.md
# Completar .env y añadir registros a whitelist.md; ambos son privados.
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

La documentación interactiva queda en `http://127.0.0.1:8000/docs`. No se necesita
configurar Azure OpenAI para usar las rutas de verificación del calendario.

## Configurar el acceso al calendario

- `CALENDAR_ACCESS_SERVICE_KEY`: clave aleatoria de al menos 32 caracteres para
  el servicio del agente. Backend y agente leen el mismo `project/.env`.
- `CALENDAR_ACCESS_CODE_SECRET`: otro secreto aleatorio de al menos 32 caracteres,
  exclusivo del backend; protege los verificadores de códigos persistidos.
- `CALENDAR_ACCESS_DB`: SQLite, por defecto `data/calendar-access.sqlite3` relativo
  a `project/`. Usar almacenamiento persistente y restringido al backend.
- `CALENDAR_WHITELIST_PROVIDER`: `file` (predeterminado) o `http`.
- `CALENDAR_WHITELIST_FILE`: `whitelist.md` por defecto, relativo a `project/`.
  Contiene los registros; los correos de la whitelist no se configuran en `.env`.
- `CALENDAR_WHITELIST_URL` y `CALENDAR_WHITELIST_API_KEY`: solo para el proveedor
  `http`, cuando se conecte un sistema externo.
- `CALENDAR_MAIL_PROVIDER`: `gmail` para enviar por Gmail API o `smtp` para usar
  un servidor SMTP. Si no se indica, se conserva SMTP.
- `CALENDAR_SMTP_HOST`, `CALENDAR_SMTP_PORT`, `CALENDAR_SMTP_SECURITY`: servidor
  de correo y modo TLS (`starttls` con 587, o `ssl` con 465).
- `CALENDAR_SMTP_USERNAME` y `CALENDAR_SMTP_PASSWORD`: credenciales SMTP, cuando
  el proveedor las requiera. Configurar ambos o ninguno.
- `CALENDAR_SMTP_FROM`: dirección de envío autorizada por el proveedor, sin nombre
  visible. `CALENDAR_SMTP_SENDER_NAME` permite un nombre visible opcional; por
  defecto queda vacío. El asunto y la plantilla no identifican una empresa.

Generar cada secreto por separado con `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
No reutilizar la credencial externa de la whitelist para el agente.

## Enviar con Gmail API

Con Gmail no se necesitan contraseña de correo ni credenciales SMTP. Habilitar
Gmail API en el mismo proyecto de Google Cloud que utiliza el cliente OAuth.
Configurar en el `.env` privado del backend:

```dotenv
CALENDAR_MAIL_PROVIDER=gmail
GOOGLE_ACCOUNT_EMAIL=<cuenta de Google autorizada>
CALENDAR_GMAIL_CLIENT_FILE=calendar_assistant/secrets/google_oauth_client.json
CALENDAR_GMAIL_TOKEN_FILE=secrets/gmail_token.json
```

Desde `project/`, autorizar una vez:

```sh
python -m app.authorize_gmail
```

El navegador solicita el permiso `gmail.send` para la cuenta configurada. El
usuario debe aceptar el consentimiento de Google; habilitar la API no concede
este permiso. No se solicita lectura del buzón. El cliente OAuth puede reutilizarse,
pero el token de envío se guarda por separado en `project/secrets/`, excluido de
Git y con permisos 600. El token de Calendar no se modifica.

Gmail envía desde la cuenta autorizada o sus alias permitidos. Seleccionar esa
misma cuenta en el consentimiento. El backend reutiliza la plantilla HTML y la
alternativa de texto, renueva tokens vencidos y exige el identificador de aceptación
de Gmail antes de informar éxito. No reintenta automáticamente un envío ambiguo.
Se conservan los límites de códigos y reenvíos; también aplican las cuotas de Gmail.

### Whitelist privada y futura base de datos

Hay una única configuración local: `project/.env`. Backend, agente, MCP y comandos
OAuth usan esa ubicación explícita, independientemente del directorio de ejecución.
Las variables del proceso tienen prioridad. El agente solo carga sus variables;
las credenciales del correo y de la whitelist y el secreto de verificación son del backend.
No crear otro `.env` o `.env.local` dentro de `calendar_assistant/`.

Los registros se guardan en `project/whitelist.md`, excluido de Git. Copiar la
plantilla vacía `project/whitelist.example.md` y completar esta tabla en la copia
privada (el ejemplo siguiente usa una dirección ficticia):

```markdown
| email | name | enabled |
| --- | --- | --- |
| persona@example.com | Persona | true |
```

Conservar la cabecera y el separador; `enabled` acepta `true` o `false`. Cada correo
debe ser único. Una tabla vacía no habilita a nadie. El archivo se consulta en cada
verificación y operación: deshabilitar un registro revoca el acceso en la siguiente
consulta. Un archivo ausente, ilegible o inválido bloquea el acceso como `unavailable`.
El backend no expone rutas para editar la whitelist.

El contrato `Whitelist.lookup(email) -> RegisteredContact | None` vive en
`services/calendar_whitelist.py`. `MarkdownWhitelist` implementa el almacenamiento
actual; `HTTPWhitelist` conserva la integración externa. Para migrar a una base de
datos, implementar ese mismo contrato y registrarlo en `configured_whitelist()`.
El agente, las rutas y el flujo de códigos no necesitan cambiar. La base SQLite
actual sigue almacenando sesiones y eventos de verificación, no los registros.

Iniciar únicamente el backend y el agente; ya no hace falta un servidor de whitelist
local separado. En `project/.env`, usar `CALENDAR_WHITELIST_PROVIDER=file` y configurar
`CALENDAR_ACCESS_URL` con el puerto del backend. Las credenciales y los registros
reales permanecen fuera del repositorio; solo se versionan las plantillas vacías.

Referencias: [envío por Gmail API](https://developers.google.com/workspace/gmail/api/guides/sending)
y [permiso de envío](https://developers.google.com/workspace/gmail/api/auth/scopes).

El template está en `templates/calendar_code.html`. Incluye únicamente el código,
su vigencia y un aviso para quien no lo haya solicitado, además de una alternativa
de texto simple. Su diseño es neutro, sin marca ni referencias al agente o la llamada.

El contrato del repositorio, la API externa, las rutas internas y los límites están en
[Verificación del correo](../calendar_assistant/VERIFICACION_CORREO.md). La forma
real del endpoint externo aún debe acordarse; el adaptador queda configurable.

## Pruebas

Desde `project/`, en el entorno del backend:

```sh
python -m pip install -r app/requirements-dev.txt
python -m pytest tests -q
```

Las pruebas usan una whitelist y un buzón ficticios; no envían correos ni acceden
al calendario real. Cubren permisos, vencimiento, reenvíos, consumo único,
concurrencia, persistencia, límites y fallas del proveedor.

Desde `project/calendar_assistant/`, para comprobar las herramientas del agente:

```sh
uv run pytest -q
uv run ruff format --check src tests
uv run ruff check src tests
```

El envío real requiere la autorización de Gmail o la configuración de SMTP, según
el proveedor elegido. El endpoint externo solo se necesita con el proveedor `http`.
SQLite soporta esta instalación local; varias réplicas necesitan compartir un
almacenamiento transaccional para conservar los límites y la autorización.
