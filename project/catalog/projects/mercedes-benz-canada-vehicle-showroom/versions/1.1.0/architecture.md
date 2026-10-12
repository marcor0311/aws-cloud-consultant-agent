# Arquitectura | Sitio de exhibición de vehículos y captación de clientes para Mercedes-Benz Canada | 1.1.0

**Estado:** proyecto histórico en producción; snapshot documental · **Diagrama:** `architecture.drawio`

## Alcance y trazabilidad

El sistema descrito corresponde a un proyecto histórico en producción. Este archivo es una reconstrucción de referencia del catálogo, no evidencia as-built completa. Los módulos Terraform y perfiles que siguen son ejemplos del catálogo y no prueban por sí solos qué versiones se desplegaron. Fechas de producción, releases y detalles no documentados quedan por recuperar.

## Cambios de esta versión

En el catálogo, este snapshot incorpora los cambios de módulos y perfiles indicados en `../../CHANGELOG.md`; no representa una comparación verificada con la release desplegada.

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

- S3 bloquea acceso público, requiere TLS y cifra datos; KMS administrado por cliente es opcional y requiere política/rotación aprobadas.
- DynamoDB usa cifrado y recuperación a un punto en el tiempo; claves, TTL y patrones de acceso se confirman con propietarios de datos.
- IAM de Lambda, identidad de usuario/operador, secretos, WAF, auditoría y manejo de información personal no están documentados en el snapshot as-built disponible.
- El sistema de pago y su tratamiento PCI no están descritos en este snapshot; no guardar datos de tarjeta.

## Disponibilidad y operación

- Validar cuotas, concurrencia, capacidad de datos y costos con pruebas representativas y métricas del negocio.
- Acordar RTO/RPO, backups/restauración, retención de logs, alertas, guardias y procedimiento de recuperación.
- Integraciones externas y despliegues descritos como dependencias no son creados por el Terraform de esta revisión.

## Configuración representada y datos por recuperar

| Decisión | Criterio | Estado |
|---|---|---|
| Perfil de API | `throttling_100rps_burst_200`; el valor real desplegado no está registrado. | Perfil representado en catálogo |
| Perfil S3 | `private_versioned_90d`; la configuración real desplegada no está registrada. | Perfil representado en catálogo |
| Perfil DynamoDB | `on_demand`; el patrón real de acceso, consistencia, índices y costo no está registrado. | Perfil representado en catálogo |
| Integraciones, identidad y continuidad | Responsables, interfaces, seguridad y SLA no registrados en esta referencia. | No registrado en este expediente |

## Límites de esta revisión

La estimación no equivale a prueba de capacidad. La tabla de perfiles refleja la composición documental del catálogo, no una declaración del perfil realmente desplegado. Recuperar la arquitectura as-built y su historial de releases antes de tomar decisiones operativas o reproducir infraestructura. No usar esta composición para aplicar cambios a producción.
