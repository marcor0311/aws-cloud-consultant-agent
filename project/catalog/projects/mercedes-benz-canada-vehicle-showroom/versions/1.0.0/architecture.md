# Arquitectura | Sitio de exhibición de vehículos y captación de clientes para Mercedes-Benz Canada | 1.0.0

**Estado:** snapshot documental histórico; sustituido en el catálogo por 1.1.0 · **Diagrama:** `architecture.drawio`

## Alcance y trazabilidad

El sistema descrito corresponde a un proyecto histórico en producción. Este archivo es una reconstrucción de referencia del catálogo, no evidencia as-built completa. Los módulos Terraform y perfiles que siguen son ejemplos del catálogo y no prueban por sí solos qué versiones se desplegaron. Fechas de producción, releases y detalles no documentados quedan por recuperar.

## Cambios de esta versión

Versión inicial del diseño y composición. Ver `../../CHANGELOG.md` para las diferencias introducidas en 1.1.0.

## Propósito

Presentar la gama de vehículos, sus especificaciones y contenido de marca; dirigir al cliente potencial al concesionario adecuado y transferir solicitudes al CRM corporativo.

## Carga de diseño

7.000 sesiones/día en operación habitual; hasta 25.000 durante lanzamientos/campañas; pico de diseño de 1.500 sesiones simultáneas y hasta 350 formularios de interés/día de campaña. Estas cifras de diseño no están asociadas en este expediente a telemetría histórica.

## Componentes y propiedad

| Componente | Responsabilidad y estado |
|---|---|
| Amazon CloudFront + Amazon S3 | Distribución del sitio y galerías desde almacenamiento privado. La distribución/CDN no está incluida en el snapshot Terraform de referencia del catálogo. |
| Amazon API Gateway HTTP API + AWS Lambda | Búsqueda del catálogo y envío de leads. El código de función y el rol desplegados no están descritos en este snapshot. |
| Amazon DynamoDB | Almacén temporal/idempotente solo si el CRM no ofrece una interfaz durable; el uso desplegado de almacenamiento temporal no está registrado en el as-built disponible. |
| Catálogo maestro, CMS, CRM y red de concesionarios | Sistemas externos y sistemas de registro; contratos e interfaces históricas no registrados en este expediente. |

## Flujo de datos

1. Cliente → CloudFront → sitio, contenido e imágenes.
2. Sitio → API Gateway/Lambda → catálogo maestro para especificaciones vigentes.
3. Formulario → API Gateway/Lambda → CRM o sistema del concesionario; devolver confirmación y referencia.
4. CMS corporativo → publicación de contenido aprobada al sitio.

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
