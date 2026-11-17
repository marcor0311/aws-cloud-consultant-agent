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
