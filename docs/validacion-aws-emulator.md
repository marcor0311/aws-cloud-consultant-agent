# Validación Terraform con AWS Emulator · #21

El escenario de integración usa el S3 del catálogo al commit que fija
`project/backend/fixtures/delivery-1.json`. Usa una clave KMS desechable
creada en la misma simulación. El repositorio consumidor aporta región,
etiquetas y estado. El baseline sigue pendiente de aprobación.

| Alcance | Comprobación |
| --- | --- |
| S3 | Bucket, acceso público bloqueado, ownership, política TLS, versionado y cifrado KMS |
| KMS | Creación de clave local para satisfacer la dependencia del módulo |
| Terraform | Formato, init, validate, plan, apply, lectura del output, plan posterior y destroy |
| Seguridad y políticas | Trivy y comprobaciones del plan para cifrado, etiquetas y bloqueo público |
| Pendiente | DynamoDB, API Gateway/Lambda, retención y logging opcionales, y controles efectivos de AWS |

Los estados `passed`, `failed` y `not_run` se registran por comprobación.
El JSON contiene versiones, recursos previstos, intervalo y referencia a la
corrida. Los detalles de fallos se consultan en la salida. Un fallo de API
requiere confirmar su origen antes de registrarlo como limitación del emulador.
La prueba con emulador tiene alcance de integración y no acredita cumplimiento
de IAM, KMS, políticas de S3 ni despliegue en AWS.

## Ejecutar

Con Docker en modo de contenedores Linux amd64, Terraform 1.14.8, Trivy
0.76.1 y las dependencias Python del backend instaladas, desde la raíz:

```powershell
docker build -t pswe07-aws-emulator "project/agents/5. terraform agent"
cd project/backend
python -m app.delivery.emulator
```

En GitHub Actions, el workflow **Integración Terraform con AWS Emulator** deja
`evidence.json` como artefacto, también ante un fallo de la prueba. El script
usa un contenedor por ejecución, el certificado y credenciales efímeras del
emulador, endpoints de S3/KMS/STS en loopback y estado temporal. Intenta
destruir la infraestructura incluso si falla el apply y elimina el contenedor.

Con PostgreSQL inicializado, importar el JSON con un UUID de entrega nuevo:

```powershell
python -m app.delivery run --input fixtures/delivery-1.json --evidence ../generated/emulator/evidence.json
```

La evidencia queda adjunta a la entrega y disponible para el informe. Para un
proyecto real, el PR de infraestructura debe ir al repositorio del proyecto,
referenciar la revisión de diseño y los insumos aprobados de FinOps, y obtener
la revisión del arquitecto antes de entregar al Engagement Manager.


## Issue 21 y regresión en GitHub Actions

El workflow ejecuta dos recorridos independientes: `delivery-1.json` y
`issue21-mock.json`. `fail-fast: false` permite conservar la evidencia de ambos
si uno falla. Cada job usa su propio PostgreSQL 16 y contenedor del emulador.
Windows no necesita importar `xxhash` ni `psycopg_binary`: las dependencias,
Terraform y la integración se ejecutan en Ubuntu con Python 3.12.

Antes del emulador se valida cada fixture con `DemoRequest`; no se relaja el
contrato ni se convierten aprobaciones ficticias en reales. La suite completa
`tests/test_delivery.py` conserva su fixture predeterminado y se ejecuta una vez
en el job `delivery-1`. Solo el recorrido existente
`test_report_revision_approval_and_close` admite `DELIVERY_TEST_INPUT` y se
ejecuta para ambos fixtures, con evidencia de su propio bucket/región/baseline.
El job de integración fija `DELIVERY_TEST_REQUIRE_DATABASE=true`: falla si falta
PostgreSQL o si los resultados JUnit incluyen omisiones. La suite offline general
conserva sus omisiones explícitas sin una URL de PostgreSQL; estas no acreditan
la integración y no sustituyen los jobs dedicados con base real.

El recorrido acredita la ejecución de los nodos de ingeniería e informe de
LangGraph, persistencia y recuperación del handoff en PostgreSQL, idempotencia,
métricas, hashes de los archivos, PDF y revisión/cierre de demostración vía
API/MCP. Las decisiones de aprobación en esa prueba son simuladas: no aprueban
infraestructura, no integran un PR y no cierran el issue #21.

### Evidencias y procedencia

Cada job publica `issue21-<fixture>-<intento>` durante 14 días, incluso ante un
fallo. Incluye `contract.json` (hash del fixture y commit), `evidence.json`
(contrato compatible con el informe), `execution.json` (intervalos medidos por
comprobación), logs de comandos, JUnit y `cleanup.txt`. Si el recorrido del
informe termina, `delivery/` contiene entrada con UUID de prueba, entrega,
handoff, métricas, archivos Terraform, decisiones y PDFs con sus hashes en JSON.
Un fallo temprano puede dejar evidencia parcial; su ausencia no significa éxito.
No se exportan archivos de credenciales, certificados privados, planes ni estado
Terraform. La salida JSON de `terraform show` se usa en memoria y no se archiva.

Arquitectura, FinOps, costos y tiempos anteriores son **simulados**. Las
comprobaciones ejecutadas, PDFs y mediciones de ingeniería/informe son **reales**
dentro del entorno local emulado. El LT/PT de ingeniería mide la preparación y
persistencia del handoff; no incorpora la duración previa de Terraform. Los
intervalos técnicos se conservan aparte en `execution.json`. El gasto AWS real
sigue sin estar disponible; no se consultan precios ni servicios AWS reales.
El baseline fijado sigue pendiente de aprobación, aunque las pruebas pasen.

### Seguridad, fallos y limpieza

Trivy HIGH/CRITICAL y las políticas del plan deben pasar antes de `apply`.
Se distinguen categorías de Terraform, seguridad, política, integración,
conexión y limpieza. Una categoría de fallo no demuestra por sí misma una
limitación del emulador: se debe revisar el log y reproducir su causa.

El runner elimina variables AWS/TF heredadas para los comandos y usa únicamente
las credenciales efímeras del emulador y endpoints TLS en loopback. No se añaden
secrets AWS, OIDC ni permisos `id-token`. Tras intentar `apply`, `finally`
ejecuta `destroy` y exige un estado vacío. Otro `finally` elimina el contenedor,
también si falla su arranque. El paso `if: always()` elimina como respaldo solo
el nombre exclusivo de esa corrida; nunca purga otros contenedores. Los esquemas
PostgreSQL de prueba se eliminan incluso si falla la migración. Un fallo de
limpieza hace fallar el job. Una terminación abrupta del runner puede impedir
los pasos de limpieza: el aislamiento final depende del runner hospedado efímero,
no de una garantía de que `destroy` haya terminado.

### Reproducir en Ubuntu

Desde `project/backend`, con PostgreSQL aislado de pruebas y las herramientas
indicadas arriba disponibles:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_delivery.py -q
FIXTURE=issue21-mock  # Repetir con delivery-1 para la integración original.
python -m app.delivery.emulator --input "fixtures/$FIXTURE.json" \
  --output "../generated/issue21/$FIXTURE/evidence.json"
DELIVERY_TEST_INPUT="fixtures/$FIXTURE.json" \
DELIVERY_TEST_EMULATOR_EVIDENCE="../generated/issue21/$FIXTURE/evidence.json" \
DELIVERY_TEST_OUTPUT="../generated/issue21/$FIXTURE/delivery" \
python -m pytest tests/test_delivery.py::test_report_revision_approval_and_close -q
```

La prueba exige un `run_url` real dentro de Actions. Fuera de Actions admite
evidencia local sin URL y el informe la identifica como corrida local; no se
deben inventar variables `GITHUB_*` para atribuirla a una ejecución remota.
Para una demostración local sin evidencia se omite
`DELIVERY_TEST_EMULATOR_EVIDENCE`.

Los cambios locales y el fixture deben estar versionados y publicados antes de
que Actions pueda ejecutarlos. Publicar la branch requiere autorización del
usuario. Después se puede disparar exclusivamente la branch de trabajo:

```powershell
gh workflow run aws-emulator.yml --repo marcor0311/aws-cloud-consultant-agent --ref entrega2issue21y22
gh run list --repo marcor0311/aws-cloud-consultant-agent --workflow aws-emulator.yml --branch entrega2issue21y22 --limit 5
gh run watch RUN_ID --repo marcor0311/aws-cloud-consultant-agent --exit-status
gh run download RUN_ID --repo marcor0311/aws-cloud-consultant-agent --dir evidence/issue21
```
