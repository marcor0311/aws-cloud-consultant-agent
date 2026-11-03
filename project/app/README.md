# Backend de la consultora

FastAPI conserva las rutas de agentes existentes y agrega verificación por correo
para Calendar Assistant. La whitelist es externa y se consulta en modo de lectura.
El backend genera códigos, envía correos y autoriza cada sesión de llamada.

## Ejecutar

Desde `project/`, con Python 3.10 o posterior:

```sh
python3 -m venv .venv-backend
source .venv-backend/bin/activate
python -m pip install -r app/requirements.txt
cp .env.example .env
# Completar .env con los datos reales.
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

La documentación interactiva queda en `http://127.0.0.1:8000/docs`. No se necesita
configurar Azure OpenAI para usar las rutas de verificación del calendario.

## Configurar el acceso al calendario

- `CALENDAR_ACCESS_SERVICE_KEY`: clave aleatoria de al menos 32 caracteres para
  el servicio del agente. Configurar el mismo valor en `.env.local` del agente.
- `CALENDAR_ACCESS_CODE_SECRET`: otro secreto aleatorio de al menos 32 caracteres,
  exclusivo del backend; protege los verificadores de códigos persistidos.
- `CALENDAR_ACCESS_DB`: SQLite, por defecto `data/calendar-access.sqlite3` relativo
  a `project/`. Usar almacenamiento persistente y restringido al backend.
- `CALENDAR_WHITELIST_URL` y `CALENDAR_WHITELIST_API_KEY`: endpoint de consulta y
  credencial del sistema que administra los registros. No hay rutas locales para
  dar de alta o modificar esa whitelist.
- `CALENDAR_SMTP_HOST`, `CALENDAR_SMTP_PORT`, `CALENDAR_SMTP_SECURITY`: servidor
  de correo y modo TLS (`starttls` con 587, o `ssl` con 465).
- `CALENDAR_SMTP_USERNAME` y `CALENDAR_SMTP_PASSWORD`: credenciales SMTP, cuando
  el proveedor las requiera. Configurar ambos o ninguno.
- `CALENDAR_SMTP_FROM`: dirección de envío autorizada por el proveedor, sin nombre
  visible. `CALENDAR_SMTP_SENDER_NAME` permite un nombre visible opcional; por
  defecto queda vacío. El asunto y la plantilla no identifican una empresa.

Generar cada secreto por separado con `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
No reutilizar la credencial externa de la whitelist para el agente.

El template está en `templates/calendar_code.html`. Incluye únicamente el código,
su vigencia y un aviso para quien no lo haya solicitado, además de una alternativa
de texto simple. Su diseño es neutro, sin marca ni referencias al agente o la llamada.

El contrato de la API externa, las rutas internas y los límites están en
[Verificación del correo](../calendar_assistant/VERIFICACION_CORREO.md). La forma
real del endpoint externo aún debe acordarse; el adaptador queda configurable.

## Pruebas

Desde `project/`, en el entorno del backend:

```sh
python -m pip install -r app/requirements-dev.txt
python -m pytest tests/test_calendar_access.py -q
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

La integración real requiere las credenciales del endpoint externo y de SMTP.
SQLite soporta esta instalación local; varias réplicas necesitan compartir un
almacenamiento transaccional para conservar los límites y la autorización.
