# Cómo ejecutar y evaluar la entrega 1

Guía paso a paso para Windows y PowerShell. Acompaña el avance de los issues
**#21 - Ingeniería** y **#22 - Informe ejecutivo**.

## 1. Qué demuestra esta entrega

Se ejecuta este recorrido local:

**Arquitectura y FinOps simulados → Ingeniería → entrega en PostgreSQL → Informe → PDF**

| Parte | Resultado que se puede verificar |
| --- | --- |
| Issue #21 | Valida coherencia de los insumos, prepara archivos Terraform S3 y registra la entrega de ingeniería. |
| Issue #22 | Consume la entrega, consolida costos y métricas, y genera un PDF borrador descargable. |
| Compartido | LangGraph coordina los dos componentes; PostgreSQL conserva entradas, entregas, tiempos y archivos. |

El avance es determinista: utiliza reglas y herramientas Python y no llama a un
modelo LLM. Arquitectura, costos y aprobaciones de origen son simulados y se
identifican expresamente. No despliega infraestructura AWS ni acredita las
funcionalidades completas de ambos issues.

## 2. Qué se necesita

- Windows y PowerShell, que viene incluido con Windows.
- Python **3.12**, disponible mediante el comando `python`.
- Docker Desktop iniciado, con soporte de contenedores Linux y Docker Compose.
- Internet durante la instalación de dependencias y la primera descarga de PostgreSQL.
- La carpeta completa de esta entrega, recibida como copia/ZIP o desde la rama
  `feat/delivery-1-engineering-report` cuando esté disponible en GitHub.

No se necesitan cuentas, claves ni recursos AWS, Google u OpenAI. Tampoco Node.js,
la aplicación Codex o las carpetas personales del desarrollador.

La ruta principal de esta guía usa Docker para PostgreSQL. Si ya se cuenta con
una base local PostgreSQL UTF-8, la [guía técnica](delivery-1.md) explica la
configuración mediante `DELIVERY_DATABASE_URL`.

## 3. Abrir PowerShell en la carpeta correcta

1. Si recibió un ZIP, extraiga su contenido primero.
2. Abra la carpeta del proyecto en el Explorador de archivos. Debe contener
   `README.md`, `project` y `docs`.
3. Haga clic en la barra de direcciones del Explorador, escriba `powershell`
   y presione **Enter**. Se abrirá PowerShell en esa ubicación.
4. Copie esta instrucción, péguela en esa ventana y presione **Enter**:

```powershell
Test-Path -LiteralPath '.\project\backend\fixtures\delivery-1.json'
```

Debe aparecer **`True`**. Si aparece `False`, la ventana no está en la carpeta
correcta o se recibió otra versión del proyecto. No continúe hasta corregirlo.

En los siguientes pasos, copie el contenido de cada bloque y presione **Enter**.
Si aparece un error, deténgase y consulte la sección de problemas frecuentes.

## 4. Comprobar las herramientas

En la misma ventana ejecute:

```powershell
python --version
docker --version
docker compose version
```

El primer comando debe mostrar Python 3.12.x. Los otros dos deben mostrar sus
versiones. Si Windows abre Microsoft Store o dice que no reconoce `python`,
revise su instalación antes de continuar. Docker Desktop debe estar encendido.

## 5. Preparar Python

Todavía desde la carpeta que contiene `README.md`, ejecute:

```powershell
python -m venv project/backend/.venv
.\project\backend\.venv\Scripts\python.exe -m pip install -r .\project\backend\requirements-dev.txt
```

La segunda instrucción puede tardar varios minutos. Espere a que termine y
vuelva a aparecer la línea donde se escriben instrucciones.
No es necesario activar el entorno ni cambiar políticas de PowerShell.

## 6. Encender PostgreSQL

Ejecute este bloque completo en la misma ventana:

```powershell
$env:DELIVERY_POSTGRES_PASSWORD = Read-Host 'Elija una clave para esta base local y conservela para repetir la prueba'
docker compose -f .\project\compose.delivery.yml up -d --wait
$env:DELIVERY_DATABASE_URL = 'postgresql://delivery:' + [Uri]::EscapeDataString($env:DELIVERY_POSTGRES_PASSWORD) + '@127.0.0.1:55432/delivery'
```

La primera instrucción espera que escriba una clave y presione **Enter**.
Use esa misma clave cuando vuelva a utilizar esta base, porque sus datos se
conservan entre ejecuciones. No hace falta editar archivos de configuración.

La primera descarga de PostgreSQL puede tardar. Cuando termine, compruebe:

```powershell
docker compose -f .\project\compose.delivery.yml ps
```

El servicio `postgres` debe aparecer iniciado y saludable (`healthy`).
Docker mantiene la base encendida; no necesita una segunda ventana para ella.

## 7. Ejecutar los dos componentes y exportar sus resultados

Ahora cambie a la carpeta `project/backend` y ejecute:

```powershell
Set-Location -LiteralPath '.\project\backend'
.venv\Scripts\python.exe -m app.delivery init-db
.venv\Scripts\python.exe -m app.delivery run --input .\fixtures\delivery-1.json --output ..\generated\delivery-demo
```

El primer comando Python debe indicar:

```text
Esquema de entrega inicializado.
```

El segundo debe terminar con un resultado similar a este:

```json
{"delivery_id": "447bfbe9-2bd5-4e96-a786-0ca9875e1d71", "status": "draft_ready", "files_exported": 4}
```

**`draft_ready` significa que el recorrido terminó y el borrador está listo.**
El archivo JSON anterior es una respuesta resumida; no es el ejemplo de entrada
que se debe pegar en la API.

## 8. Abrir y revisar el PDF

En la misma ventana ejecute:

```powershell
Invoke-Item -LiteralPath '..\generated\delivery-demo\informe-ejecutivo-v1.pdf'
```

Para abrir la carpeta de resultados:

```powershell
Invoke-Item -LiteralPath '..\generated\delivery-demo'
```

| Archivo | Función |
| --- | --- |
| `informe-ejecutivo-v1.pdf` | Borrador ejecutivo, con resultados, costos, métricas, limitaciones y fuentes. |
| `delivery.json` | Entrega completa, referencias, estados y métricas. |
| `main.tf` | Composición S3 preparada con una referencia fija al catálogo. |
| `variables.tf` | Parámetros de la composición. |
| `terraform.tfvars.example` | Valores simulados; no representa recursos existentes. |

Se exportan cuatro archivos de respaldo y, adicionalmente, `delivery.json`.

En el PDF se puede comprobar:

- Presupuesto simulado de USD 100.00 y estimación simulada de USD 24.50 por mes.
- Margen calculado de USD 75.50 y gasto real identificado como no disponible.
- Diferencia entre comprobaciones realizadas y validaciones pendientes.
- Métricas con procedencia real o simulada y fases sin mediciones disponibles.
- Revisión técnica pendiente, ausencia de PR y estado de informe borrador.

## 9. Comprobar que la misma entrega no se duplica

Ejecute nuevamente:

```powershell
.venv\Scripts\python.exe -m app.delivery run --input .\fixtures\delivery-1.json --output ..\generated\delivery-demo
```

Debe conservar el mismo `delivery_id` y devolver `draft_ready`.
La implementación recupera el resultado guardado, en vez de crear otra entrega
o regenerar el PDF. Para otra versión de los datos se requiere otro identificador.

## 10. Opcional: ejecutar las pruebas automáticas del avance

Con la base encendida y desde `project/backend`, ejecute:

```powershell
$env:DELIVERY_TEST_DATABASE_URL = $env:DELIVERY_DATABASE_URL
.venv\Scripts\python.exe -m pytest tests/test_delivery.py -q
```

Resultado esperado para esta versión: **21 pruebas correctas**.
Si se omiten pruebas (`skipped`), revise la variable de conexión: una omisión
no acredita integración con PostgreSQL.

Las pruebas crean y eliminan sus propios esquemas de prueba; no eliminan la
entrega de demostración. Cubren contrato, métricas, bloqueo por insumos
incoherentes, descargas, repetición, concurrencia y recuperación tras fallos.

La regresión completa y sus dos fallos preexistentes de permisos POSIX de Gmail
en Windows están documentados en la [guía técnica](delivery-1.md#pruebas).

## 11. Opcional: probar desde el navegador

### Iniciar la API

En la misma ventana, desde `project/backend`, ejecute:

```powershell
.venv\Scripts\python.exe -m uvicorn app.demos.delivery:app --host 127.0.0.1 --port 8011
```

Espere un mensaje que incluya `Uvicorn running on http://127.0.0.1:8011`.
La ventana permanecerá ocupada mientras la API esté encendida; es normal.

### Preparar la página y copiar la entrada correcta

1. Abra el navegador y escriba `http://127.0.0.1:8011/docs`.
2. Despliegue **POST /api/delivery/runs** y pulse **Try it out**.
3. En el Explorador de archivos entre en la carpeta del proyecto, después en
   `project`, luego en `backend` y `fixtures`.
4. Abra `delivery-1.json` con Bloc de notas u otro editor de texto.
5. Dentro del archivo presione **Ctrl + A** y luego **Ctrl + C**.
6. Vuelva al navegador, haga clic dentro de **Request body**, presione
   **Ctrl + A** y luego **Ctrl + V**.
7. Pulse **Execute**.

El cuadro debe contener el archivo completo: comienza con `{` e incluye
`schema_version`, `architecture` y `finops`. No pegue instrucciones PowerShell
ni la respuesta resumida del paso 7. Después de copiar el JSON no copie otra
cosa antes de pegarlo, porque reemplazaría el contenido del portapapeles.

En **Server response** debe aparecer código **200** y `"status": "draft_ready"`.
Para comprobar el rechazo de una entrada incompleta, sustituya temporalmente
el contenido de **Request body** por `{}` y pulse **Execute**: debe devolver **422**.
Esto no modifica el archivo de ejemplo.

También se incluyen operaciones GET para consultar la entrega y descargar sus
archivos utilizando los identificadores devueltos en la respuesta.

## 12. Apagar los servicios

1. Si inició la API, presione **Ctrl + C** en PowerShell y espere a que reaparezca
   la línea para escribir.
2. Desde la carpeta `project/backend`, ejecute:

```powershell
docker compose -f ..\compose.delivery.yml down
```

Eso detiene los contenedores de esta demostración y conserva el volumen de
datos. Para repetir otro día, abra PowerShell desde la carpeta raíz y siga
desde el paso 6, usando la misma clave de la base.

## Problemas frecuentes

| Situación | Qué revisar |
| --- | --- |
| La comprobación inicial devuelve `False`. | Abrir PowerShell en la carpeta que contiene el README y la carpeta `project`. |
| No se reconoce `python` o `docker`. | Revisar la instalación y abrir una nueva ventana de PowerShell. |
| Docker no conecta con su motor. | Iniciar Docker Desktop y esperar a que esté disponible. |
| El puerto 55432 está ocupado. | Detener una demostración anterior de PostgreSQL que use ese puerto o consultar antes de cerrar otros procesos. |
| Falla la autenticación de PostgreSQL. | Usar la misma clave con la que se creó esta base; cambiar la variable no cambia la clave de un volumen existente. |
| La API responde 422 con `json_invalid` o `Expecting value`. | Reemplazar todo Request body por el contenido del archivo JSON, no por comandos ni resultados. |
| La API responde 409. | Se reutilizó un identificador con datos diferentes; usar el ejemplo original o un UUID nuevo para otra versión. |
| Aparece `blocked`. | Revisar la explicación en `error`; no significa que se haya generado un informe exitoso. |

## Límites de la evaluación

Esta guía permite evaluar el **primer avance de ambos issues**. Quedan pendientes
las entregas reales de Arquitectura/FinOps, validaciones Terraform y seguridad,
el despliegue local acordado, PR/revisión del arquitecto, MCP, versiones y
aprobación del informe y cierre. Los datos simulados no sustituyen esas evidencias.

No ejecutar `terraform apply` para seguir esta guía: no forma parte de esta
demostración. El detalle de arquitectura y contrato está en
[Entrega 1: ingeniería e informe ejecutivo](delivery-1.md).
