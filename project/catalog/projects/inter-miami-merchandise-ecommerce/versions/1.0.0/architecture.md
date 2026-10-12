# Arquitectura | Plataforma de comercio electrónico de merchandising oficial para Inter Miami CF | 1.0.0

**Estado:** snapshot documental histórico; sustituido en el catálogo por 1.1.0 · **Diagrama:** `architecture.drawio`

## Alcance y trazabilidad

El sistema descrito corresponde a un proyecto histórico en producción. Este archivo es una reconstrucción de referencia del catálogo, no evidencia as-built completa. Los módulos Terraform y perfiles que siguen son ejemplos del catálogo y no prueban por sí solos qué versiones se desplegaron. Fechas de producción, releases y detalles no documentados quedan por recuperar.

## Cambios de esta versión

Versión inicial del diseño y composición. Ver `../../CHANGELOG.md` para las diferencias introducidas en 1.1.0.

## Propósito

Permitir descubrir productos, revisar disponibilidad y completar compras seguras desde web y móvil, con catálogo y estado de órdenes integrados a los sistemas comerciales.

## Carga de diseño

20.000 sesiones/día en operación habitual; hasta 100.000 sesiones en día de lanzamiento o partido de alta demanda; pico de diseño de 4.000 sesiones simultáneas. Volumen esperado: 900 órdenes/día habitual y hasta 5.000 en campaña. Estas cifras de diseño no están asociadas en este expediente a telemetría histórica.

## Componentes y propiedad

| Componente | Responsabilidad y estado |
|---|---|
| Amazon CloudFront + Amazon S3 | Distribución del frontend e imágenes; bucket privado con acceso de origen controlado. La distribución y su Origin Access Control no están representados en el Terraform de referencia del catálogo. |
| Amazon API Gateway HTTP API + AWS Lambda | API de catálogo y órdenes. El código de función y el rol desplegados no están descritos en este snapshot. |
| Amazon DynamoDB | Catálogo, carrito y referencias de órdenes; claves, índices e idempotencia reales no están documentados en este snapshot. |
| Proveedor de pagos, inventario y fulfillment | Sistemas externos; no están incluidos en el snapshot Terraform de referencia. |

## Flujo de datos

1. Cliente → CloudFront → frontend y contenido desde S3 privado.
2. Navegador → API Gateway → Lambda → catálogo/carrito/órdenes en DynamoDB.
3. Checkout → proveedor de pagos externo; guardar únicamente referencias y estados.
4. Lambda integra inventario, envíos y notificaciones mediante APIs autorizadas.

## Seguridad y privacidad

- S3 bloquea acceso público y cifra objetos. Esta versión no aplica una política explícita que deniegue HTTP inseguro; eso se añade en el baseline 1.1.0.
- DynamoDB cifra datos y habilita recuperación a un punto en el tiempo; claves, TTL y patrón de acceso deben confirmarse con los propietarios de datos.
- El soporte opcional de KMS administrado por el cliente queda incorporado en los baselines 1.1.0.
- IAM de Lambda, identidad de usuario/operador, secretos, WAF, auditoría y manejo de información personal no están documentados en el snapshot as-built disponible.
- El sistema de pago y su tratamiento PCI no están descritos en este snapshot; no guardar datos de tarjeta.

## Disponibilidad y operación

- Validar cuotas, concurrencia, capacidad de datos y costos con pruebas representativas y métricas del negocio.
- Acordar RTO/RPO, backups/restauración, retención de logs, alertas, guardias y procedimiento de recuperación.
- Integraciones externas y despliegues descritos como dependencias no son creados por el Terraform de esta revisión.

## Configuración representada y datos por recuperar

| Decisión | Criterio | Estado |
|---|---|---|
| API Gateway HTTP API | Baseline 1.0.0 sin perfil de throttling seleccionable. | Inicial |
| S3 privado | Versionado habilitado por defecto; retención no configurada. | Inicial |
| DynamoDB | Modalidad bajo demanda. | Inicial |
| Integraciones, identidad y continuidad | Responsables, interfaces, seguridad y SLA no registrados en esta referencia. | No registrado en este expediente |

## Límites de esta revisión

La estimación no equivale a prueba de capacidad. La tabla de perfiles refleja la composición documental del catálogo, no una declaración del perfil realmente desplegado. Recuperar la arquitectura as-built y su historial de releases antes de tomar decisiones operativas o reproducir infraestructura. No usar esta composición para aplicar cambios a producción.
