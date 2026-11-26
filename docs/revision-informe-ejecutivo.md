# Revisión del informe ejecutivo · #22

El informe por expediente consolida registros existentes sin ejecutar ingeniería.
Puede generarse antes de completar #21: los faltantes se muestran y bloquean el
cierre real. La entrega técnica de demostración es opcional y conserva su
identificación de arquitectura y FinOps simulados. El recorrido anterior de
ingeniería e informe continúa disponible exclusivamente como demostración.

En GitHub Actions, el workflow **Integración Terraform con AWS Emulator**
también ejecuta el recorrido del informe con el JSON de la misma corrida.
Los PDF y sus respaldos se conservan dentro del artefacto `issue21-<fixture>-<intento>`.

## Configurar

Desde `project/backend`, con las dependencias y PostgreSQL local configurados
según [Entrega 1](delivery-1.md):

```powershell
$env:DELIVERY_ENGAGEMENT_MANAGER = 'Nombre del operador de demostración'
python -m app.delivery init-db
python -m app.delivery.mcp
```

El último comando es para un cliente MCP con transporte STDIO. Configurar en
el cliente el ejecutable de Python del backend, los argumentos
`-m app.delivery.mcp` y las variables privadas `DELIVERY_DATABASE_URL` y
`DELIVERY_ENGAGEMENT_MANAGER`. La identidad registrada viene de esa configuración
del operador local.

| Herramienta | Acción |
| --- | --- |
| `generar_informe` | Consolidar un expediente con `report_id` y `case_id`; la entrada anterior `fixtures/delivery-1.json` conserva el ejemplo |
| `consultar_informe` | Consultar revisión vigente, tiempos, historial y URI de PDF |
| `registrar_decision_informe` | Guardar ajustes, revisión, aprobación o presentación |
| Recurso `delivery://pdf/{entrega_id}/{archivo_id}` | Leer el PDF descargable en un cliente MCP que admita recursos |

## Informe independiente del issue 21

Configurar también `WORKFLOW_DATABASE_URL` para la base PostgreSQL existente del
proceso. `DELIVERY_DATABASE_URL` conserva los informes; ambas pueden apuntar a la
misma base. Usar como `DELIVERY_ENGAGEMENT_MANAGER` el identificador exacto del
responsable registrado en `workflow_projects`, no un nombre nuevo para esta sesión.
El runtime es local y de un único operador; esto no añade autenticación empresarial.
El MCP no compone proveedores de Google, Slack o IA ni inicia workers.

1. Consultar `listar_expedientes_informe` para seleccionar un `case_id` propio.
2. Llamar `generar_informe` con la nueva entrada:

   ```json
   {
     "entrada": {
       "report_id": "3322a904-81a4-4dd3-ab1d-8402da256ed9",
       "case_id": "expediente-existente"
     }
   }
   ```

3. Opcionalmente añadir `engineering_delivery_id` con una entrega persistida del
   mismo `project_id`. Se verifican sus archivos por hash y se mantiene su procedencia
   simulada. Nunca se vuelve a ejecutar el nodo de ingeniería.
4. Consultar el informe y descargar `pdf_uri` y `sources_uri`. Este último recurso
   JSON contiene proyecto, presupuesto de dirección si existe, decisiones,
   manifiesto, entrega adjunta y mediciones que respaldan el documento. El PDF
   identifica el SHA-256 de ese respaldo.
5. Solicitar cambios con `request_changes`. Para `revise`, enviar además `sections`
   con una o más claves `results`, `risks`, `next_steps`. El contenido reemplaza la
   sección correspondiente, conserva las demás y genera una versión nueva.
6. `approve` aprueba exactamente esa versión como **informe parcial**. Se pueden
   pedir cambios sobre un informe aprobado, invalidando su aprobación vigente.
   El PDF anterior permanece disponible para auditoría.

Las fuentes se congelan al primer uso de `report_id`, incluso si falla el renderizado.
Repetir la petición recupera el mismo informe. Para incorporar información posterior
del expediente, usar otro `report_id`; no se reemplazan silenciosamente las fuentes
de una revisión aprobada. Los UUID del informe y de la entrega técnica son distintos.

La API local de revisión añade `POST /api/delivery/reports` con el contenido de
`entrada` como cuerpo. Las consultas y decisiones reutilizan las rutas existentes
usando el `delivery_id` devuelto (igual al `report_id` solicitado). Las nuevas rutas
solo se montan en la demostración de loopback, igual que las decisiones existentes.
La lectura, decisión y descarga de un informe por expediente exigen el operador
local con que se creó. No exponer esta API fuera de loopback.

### Métricas y límites

- LT se obtiene de límites registrados de cada fase; las fases abiertas se marcan
  en curso y las ausentes muestran `null` / "Sin medición".
- PT suma esfuerzo registrado por actor, uniendo sus intervalos superpuestos.
  La duración activa une todos los intervalos, sin sumar dos veces fases de detalle.
- Se muestran esfuerzo humano/agente, sesiones abiertas, ciclos de cambios y
  espera entre creación y recepción de cada handoff, con recepción pendiente explícita.
- El workflow actual no etiqueta intervalos como espera o retrabajo: esas duraciones
  de fase quedan sin medición. El tiempo restante se conserva sin clasificar.
- El presupuesto de dirección no declara periodo. No se compara automáticamente
  con la estimación mensual simulada de FinOps. El gasto real sigue sin información.
- `metrics` es la instantánea del expediente al corte. `report_activity_metrics`
  muestra aparte la generación y las revisiones del PDF; no se inventa tiempo de
  lectura humana ni se infiere el LT global sumando fases.

`record_presentation` devuelve conflicto para estos informes parciales. No modifica
el estado del proceso ni fabrica una entrega aprobada de ingeniería. La conexión
de la entrega real de #21 y el cierre definitivo del expediente siguen pendientes.

## Revisar y cerrar la demostración anterior

1. Consultar el borrador y tomar `report.version` y `report.artifact.sha256`.
2. Enviar una decisión con un `decision_id` UUID nuevo, la versión, su SHA-256,
   la acción `request_changes` y los cambios solicitados en `detail`.
3. Enviar `revise` sobre la misma revisión con la actualización ejecutiva en
   `detail`. El backend guarda una nueva versión y conserva el PDF anterior.
4. Confirmar `approve` sobre la revisión vigente. La copia PDF aprobada
   incluye el operador, la fecha, la decisión y el hash del PDF revisado.
5. Tras presentar el informe, registrar `record_presentation` con la referencia
   de la sesión o acta. Eso cambia la entrega local a `closed`.

La API de demostración en loopback permite el mismo recorrido en una interfaz
web. Ejecutar `python -m uvicorn app.demos.delivery:app --host 127.0.0.1 --port 8011`
y usar [OpenAPI local](http://127.0.0.1:8011/docs). Las rutas de revisión no se
montan en el backend HTTP principal.

| Operación | Ruta |
| --- | --- |
| Consultar informe | `GET /api/delivery/runs/{delivery_id}/report` |
| Registrar decisión | `POST /api/delivery/runs/{delivery_id}/report/decisions` |
| Descargar documento | `GET /api/delivery/runs/{delivery_id}/artifacts/{artifact_id}` |

La consulta del informe incluye Lead Time, Process Time, esperas registradas
y retrabajo, con desglose humano y agente. El tiempo de revisión humana sin
medición permanece sin clasificar. Cada PDF se conserva como instantánea.
