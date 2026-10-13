# Ficha de proyecto | Plataforma SkiPass e integración operativa de cinco estaciones de Verbier 4 Vallées

**Tipo:** proyecto histórico (`consulting_project_reference`).  
**Producción:** en operación (`in_production`).  
**Versión documental:** 1.1.0.

## Organización y operación

- **Organización:** Verbier 4 Vallées y los operadores participantes en el servicio SkiPass.
- **Ubicación:** cantón de Valais, Suiza.
- **Actividad:** operación turística y de esquí, venta de pases y coordinación de accesos y servicios de montaña.
- **Equipo de operación:** 45 personas en atención, operación central y tecnología, y 320 personas estacionales distribuidas en las estaciones.
- **Usuarios y capacidad:** la plataforma coordina una capacidad de 24.000 visitantes diarios entre cinco estaciones y procesa hasta 18.000 reservas digitales por día. Los canales digitales admiten 3.000 sesiones simultáneas durante la apertura y la venta de pases.

La consultoría implementó una plataforma SkiPass en producción para conectar las reservas digitales con la operación de cinco estaciones: Verbier, La Tzoumaz, Nendaz, Veysonnaz y Thyon. El dominio de Verbier 4 Vallées comprende seis estaciones; esta integración atiende las cinco anteriores. La plataforma conecta los servicios en AWS con los sistemas locales de venta de pases, torniquetes y datos operativos, y reúne información meteorológica para apoyar las decisiones del personal de montaña.

## Objetivo

Unificar la disponibilidad, reserva y emisión de pases entre cinco estaciones, coordinar los accesos con los sistemas locales y mantener la continuidad operativa durante interrupciones de conectividad, incorporando las condiciones meteorológicas a la información del servicio.

## Requisitos funcionales

- Consultar disponibilidad, condiciones y estado de apertura por estación y fecha.
- Reservar, emitir y cancelar pases con control de capacidad y prevención de duplicados.
- Procesar pagos, devoluciones y notificaciones conforme a las reglas del servicio SkiPass.
- Sincronizar reservas y accesos con los sistemas locales de venta de pases y torniquetes.
- Mantener una operación local degradada durante una desconexión y reconciliar los registros al recuperar la comunicación.
- Mostrar información meteorológica con ubicación y hora de actualización; personal autorizado decide los cierres y las alertas.

## Alcance de solución

| Componente | Responsabilidad en producción | Motivo de selección | Configuración de referencia |
|---|---|---|---|
| Portal web, aplicación y Amazon CloudFront | Ofrecen consulta de disponibilidad, reservas y distribución del contenido de las estaciones. | Permiten utilizar el servicio antes de llegar a la montaña y durante la visita. | Canales adaptados a dispositivos móviles y distribución con caché. |
| Amazon API Gateway HTTP API | Expone las operaciones de reservas, disponibilidad y sincronización. | Proporciona una entrada administrada para los canales públicos y las integraciones autorizadas. | `throttling_500rps_burst_1000`: 500 solicitudes por segundo y ráfagas de 1.000. |
| AWS Lambda | Ejecuta las reglas de reservas y coordina pagos, sincronización e información meteorológica. | Separa los procesos de negocio y adapta el procesamiento a los picos de venta. | Funciones por operación con permisos limitados a sus recursos e integraciones. |
| Amazon DynamoDB | Mantiene disponibilidad, reservas y estados de sincronización. | Utiliza escrituras condicionales y transacciones para controlar concurrencia, capacidad e idempotencia. | `aws-dynamodb-single-table` / `on_demand`. |
| Amazon S3 | Almacena contenido, documentos y objetos privados de la plataforma. | Mantiene los archivos separados de las reservas y permite recuperar versiones. | `aws-private-object-storage` / `private_versioned_365d`. |
| Conectividad privada redundante y agentes locales | Comunican los servicios cloud con las cinco estaciones y conservan registros pendientes durante cortes. | Sostienen la continuidad de los accesos y la reconciliación posterior. | Comunicación autenticada, cola local durable y control de duplicados. |
| Sistemas locales de venta de pases, torniquetes y operación de remontes | Emiten o validan pases y aportan el estado operativo de cada estación. | Integran la reserva digital con la infraestructura física de montaña. | Adaptadores hacia los sistemas locales existentes. |
| Estaciones y proveedor de información meteorológica | Entregan observaciones y pronósticos para las consultas, paneles y alertas. | Aportan información actualizada para la coordinación operativa y las decisiones humanas. | Registros con ubicación, hora y control de vigencia. |

### Flujo principal

1. El visitante consulta el portal o la aplicación para elegir estación, fecha y tipo de pase.
2. La API recibe la reserva; Lambda comprueba las reglas del servicio y actualiza la disponibilidad mediante operaciones condicionales en DynamoDB.
3. El servicio procesa el pago y confirma la reserva y la emisión del pase.
4. Los servicios cloud sincronizan la información con los sistemas locales mediante conectividad privada y agentes de integración.
5. Los torniquetes validan los accesos. Durante una desconexión, el agente local conserva los registros y los reconcilia sin duplicarlos al recuperar la comunicación.
6. Los adaptadores meteorológicos actualizan las condiciones por estación; el personal autorizado revisa la información y publica cambios de apertura o alertas.

## Operación en producción

La operación central coordina las reservas, reglas de pases y atención al visitante. Los equipos de las cinco estaciones mantienen los accesos y el estado de sus servicios; tecnología supervisa las integraciones cloud y locales. La plataforma comparte la información necesaria para coordinar la operación entre estaciones.

Los agentes locales mantienen colas durables durante cortes de comunicación y aplican reconciliación con identificadores idempotentes. La disponibilidad se actualiza con control de concurrencia para evitar sobreventa. La información meteorológica muestra su hora de actualización y se identifica cuando pierde vigencia; las decisiones de cierre y reapertura permanecen a cargo del personal autorizado de montaña.

## Requisitos de calidad

- Continuidad de la validación local de pases durante interrupciones de conectividad.
- Reservas consistentes, control de capacidad y reconciliación sin registros duplicados.
- Comunicación autenticada y permisos mínimos entre los servicios cloud y las estaciones.
- Protección de datos de visitantes y procesamiento de pagos mediante servicios autorizados.
- Información meteorológica trazable por ubicación y hora, con control de vigencia y decisión humana sobre cierres.
- Seguimiento de errores de reserva, pagos y sincronización, y recuperación del contenido versionado.

## Fuentes de contexto

- [Verbier 4 Vallées: área y estaciones](https://verbier4vallees.ch/en/about-us) — contexto del dominio de esquí y sus seis estaciones.
- [Téléverbier: actividades y operación](https://verbier4vallees.ch/en/about-us) — contexto institucional y operativo de la organización.
