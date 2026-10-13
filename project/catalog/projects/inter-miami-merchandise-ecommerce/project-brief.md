# Ficha de proyecto | Plataforma de comercio electrónico de merchandising oficial para Inter Miami CF

**Tipo:** proyecto histórico (`consulting_project_reference`).  
**Producción:** en operación (`in_production`).  
**Versión documental:** 1.1.0.

## Organización y operación

- **Organización:** Inter Miami CF.
- **Ubicación:** Miami, Florida, Estados Unidos.
- **Actividad:** club de fútbol profesional con una operación comercial de uniformes, ropa, accesorios y colecciones oficiales.
- **Equipo de operación:** 18 personas: comercio digital (4), catálogo y productos (4), marketing (3), atención al cliente (4) y operaciones e inventario (3).
- **Usuarios y capacidad:** la tienda atiende 20.000 sesiones diarias en su operación habitual y dispone de capacidad para 100.000 sesiones por día y 4.000 sesiones simultáneas durante lanzamientos y partidos de alta demanda. El flujo de pedidos maneja 900 órdenes diarias en operación habitual y hasta 5.000 durante campañas.

La consultoría implementó una tienda digital que integra la compra de productos oficiales con el inventario, los pagos y la preparación de envíos. La plataforma está en producción y permite a los aficionados descubrir colecciones, elegir tallas y comprar desde computadoras y dispositivos móviles. El equipo comercial administra el catálogo y coordina las campañas sin interrumpir la atención de pedidos.

## Objetivo

Centralizar la venta digital de productos oficiales de Inter Miami CF y sostener los picos de demanda asociados a partidos, nuevas camisetas y colecciones, manteniendo una experiencia de compra ágil y un seguimiento consistente de cada pedido.

## Requisitos funcionales

- Consultar productos por categoría, talla, jugador y colección, con fotografías y disponibilidad actualizada.
- Mantener el carrito y completar el pago mediante un proveedor certificado, sin almacenar números de tarjeta en la plataforma.
- Registrar pedidos y coordinar disponibilidad, preparación y envío con los sistemas comerciales.
- Consultar el estado de las órdenes y recibir confirmaciones y notificaciones.
- Gestionar cuentas, solicitudes de atención y devoluciones conforme a las políticas de la tienda.

## Alcance de solución

| Componente | Responsabilidad en producción | Motivo de selección | Configuración de referencia |
|---|---|---|---|
| Amazon CloudFront | Distribuye la tienda y las imágenes mediante caché en ubicaciones cercanas a los clientes. | Reduce el tiempo de carga y absorbe el tráfico de contenido durante campañas. | Distribución con acceso de origen controlado a S3. |
| Amazon S3 | Almacena la interfaz web, fotografías y contenido comercial en almacenamiento privado y versionado. | Separa los archivos del procesamiento de pedidos y permite recuperar versiones de contenido. | `private_versioned_365d`. |
| Amazon API Gateway HTTP API | Expone las operaciones de catálogo, carrito y órdenes, y controla el volumen de solicitudes a la API. | Proporciona una entrada administrada para la lógica de negocio. | `throttling_500rps_burst_1000`: 500 solicitudes por segundo y ráfagas de 1.000. |
| AWS Lambda | Ejecuta la lógica de catálogo y pedidos y las integraciones comerciales. | Ajusta el procesamiento a la demanda sin administrar servidores de aplicación. | Funciones por operación con permisos limitados a los recursos que utilizan. |
| Amazon DynamoDB | Mantiene los datos de catálogo, carrito y órdenes mediante un diseño de tabla única. | Proporciona acceso de baja latencia y capacidad bajo demanda para las transacciones de la tienda. | `aws-dynamodb-single-table` / `on_demand`. |
| Servicios de pagos, inventario y envíos | Procesan el cobro y coordinan la disponibilidad, preparación y entrega de los productos. | Conectan la tienda con los servicios responsables de las operaciones comerciales. | Integraciones mediante APIs autorizadas y referencias de transacción. |

### Flujo principal

1. El aficionado accede a la tienda; CloudFront entrega la interfaz y las imágenes desde S3 privado.
2. La interfaz consulta la API para obtener productos, disponibilidad y contenido del carrito.
3. API Gateway dirige las solicitudes a Lambda, que consulta o actualiza los datos en DynamoDB.
4. El proveedor de pagos procesa el cobro; la plataforma registra la referencia de transacción y el estado del pedido.
5. Las integraciones comerciales coordinan el inventario y el envío, y la tienda comunica al cliente los cambios de estado.

## Operación en producción

Comercio digital y catálogo administran productos, tallas y colecciones. Marketing programa las campañas; atención al cliente gestiona consultas y devoluciones; operaciones e inventario coordinan la preparación de pedidos y su entrega.

Durante un lanzamiento, CloudFront mantiene la distribución del contenido, DynamoDB trabaja bajo demanda y la API aplica sus límites de solicitudes. Los cambios de contenido utilizan el versionado de S3 para facilitar la recuperación. El equipo sigue el estado de pagos, órdenes e integraciones y atiende los incidentes que afectan la compra o el despacho.

## Requisitos de calidad

- Experiencia adaptable a computadoras y dispositivos móviles, con imágenes optimizadas y navegación clara.
- Almacenamiento privado, acceso de origen controlado y permisos mínimos para las funciones de negocio.
- Procesamiento de pedidos sin duplicados ante reintentos de solicitudes o notificaciones de pago.
- Protección de los datos del cliente y procesamiento de tarjetas a cargo del proveedor de pagos.
- Seguimiento de errores y estados de integración, y recuperación de versiones del contenido publicado.

## Fuentes de contexto

- [Inter Miami CF](https://www.intermiamicf.com/) — contexto institucional de la organización.
