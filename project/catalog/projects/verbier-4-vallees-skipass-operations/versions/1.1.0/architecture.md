# Arquitectura | Plataforma SkiPass e integración operativa de cinco estaciones de Verbier 4 Vallées | 1.1.0

**Estado:** proyecto histórico en producción; snapshot documental · **Diagrama:** `architecture.drawio`

## Alcance y trazabilidad

El sistema descrito corresponde a un proyecto histórico en producción. Este archivo es una reconstrucción de referencia del catálogo, no evidencia as-built completa. Los módulos Terraform y perfiles que siguen son ejemplos del catálogo y no prueban por sí solos qué versiones se desplegaron. Fechas de producción, releases y detalles no documentados quedan por recuperar.

## Cambios de esta versión

En el catálogo, este snapshot incorpora los cambios de módulos y perfiles indicados en `../../CHANGELOG.md`; no representa una comparación verificada con la release desplegada.

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
| Perfil de API | `throttling_500rps_burst_1000`; el valor real desplegado no está registrado. | Perfil representado en catálogo |
| Perfil S3 | `private_versioned_365d`; la configuración real desplegada no está registrada. | Perfil representado en catálogo |
| Perfil DynamoDB | `on_demand`; el patrón real de acceso, consistencia, índices y costo no está registrado. | Perfil representado en catálogo |
| Integraciones, identidad y continuidad | Responsables, interfaces, seguridad y SLA no registrados en esta referencia. | No registrado en este expediente |

## Límites de esta revisión

La estimación no equivale a prueba de capacidad. La tabla de perfiles refleja la composición documental del catálogo, no una declaración del perfil realmente desplegado. Recuperar la arquitectura as-built y su historial de releases antes de tomar decisiones operativas o reproducir infraestructura. No usar esta composición para aplicar cambios a producción.
