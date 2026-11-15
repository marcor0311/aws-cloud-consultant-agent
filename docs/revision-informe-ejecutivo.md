# Revisión del informe ejecutivo · #22

Este recorrido utiliza la entrega de ingeniería persistida. Se puede generar
un informe con el ejemplo S3 o importar previamente la evidencia del #21 mediante
la [guía de AWS Emulator](validacion-aws-emulator.md). El informe identifica la
procedencia simulada de arquitectura y FinOps y los resultados de pruebas
importados, si existen. Un cierre del ejemplo se registra en la entrega local.

En GitHub Actions, el workflow **Integración Terraform con AWS Emulator**
también ejecuta el recorrido del informe con el JSON de la misma corrida.
El PDF generado se publica como `informe-ejecutivo-demostracion`.

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
| `generar_informe` | Ejecutar el ejemplo con `fixtures/delivery-1.json` como `entrada` |
| `consultar_informe` | Consultar revisión vigente, tiempos, historial y URI de PDF |
| `registrar_decision_informe` | Guardar ajustes, revisión, aprobación o presentación |
| Recurso `delivery://pdf/{entrega_id}/{archivo_id}` | Leer el PDF descargable en un cliente MCP que admita recursos |

## Revisar y cerrar

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
