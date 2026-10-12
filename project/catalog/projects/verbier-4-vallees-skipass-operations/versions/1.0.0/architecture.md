# Arquitectura | Plataforma SkiPass e integración operativa de cinco estaciones de Verbier 4 Vallées | 1.0.0

**Estado:** snapshot documental histórico; sustituido en el catálogo por 1.1.0 · **Diagrama:** `architecture.drawio`

## Alcance y trazabilidad

El sistema descrito corresponde a un proyecto histórico en producción. Este archivo es una reconstrucción de referencia del catálogo, no evidencia as-built completa. Los módulos Terraform y perfiles que siguen son ejemplos del catálogo y no prueban por sí solos qué versiones se desplegaron. Fechas de producción, releases y detalles no documentados quedan por recuperar.

## Cambios de esta versión

Versión inicial del diseño y composición. Ver `../../CHANGELOG.md` para las diferencias introducidas en 1.1.0.

## Propósito

Unificar disponibilidad y reservas SkiPass entre cinco estaciones, conectar la experiencia digital con ticketing/torniquetes locales y mantener operaciones seguras durante cortes de conectividad.

## Carga de diseño

Capacidad de planeación: 24.000 visitantes/día entre cinco estaciones; hasta 18.000 reservas digitales/día y 3.000 sesiones simultáneas en apertura/venta. Estas cifras no están respaldadas aquí por registros históricos de los operadores.

## Componentes y propiedad

| Componente | Responsabilidad y estado |
|---|---|
| Sitio/app + Amazon CloudFront | Canales públicos de reserva; experiencia web/app por definir. |
| Amazon API Gateway HTTP API + AWS Lambda | API de reservas, inventario y sincronización; La implementación Lambda, la identidad y la red no están descritas en este snapshot. |
| Amazon DynamoDB | Estado de disponibilidad y reservas con escrituras condicionales/idempotencia; transacciones e índices reales no están registrados en este snapshot. |
| Amazon S3 | Contenido y objetos privados con retención aprobada. |
| Ticketing, torniquetes, remontes y estaciones meteorológicas | Sistemas on-premise/de terceros; su integración local, conectividad y propiedad de datos no están descritas en este snapshot. |
| Proveedor meteorológico | Fuente externa de observaciones/pronóstico; alertas no accionan cierres automáticamente. |

## Flujo de datos

1. Visitante → portal → disponibilidad por estación/fecha → reserva y pase.
2. API de reserva → transacción/idempotencia → confirmación y evento de sincronización.
3. Servicios cloud ↔ conectividad privada redundante ↔ agentes y ticketing/torniquetes locales.
4. Agente local mantiene cola durable durante desconexión y reconcilia con control de duplicados.
5. Fuente meteorológica → adaptador con hora/frescura → panel/alertas; decisión de cierre humana.

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
