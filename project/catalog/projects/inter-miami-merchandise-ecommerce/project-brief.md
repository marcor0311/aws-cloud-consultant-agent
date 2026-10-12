# Ficha de proyecto | Plataforma de comercio electrónico de merchandising oficial para Inter Miami CF

**Tipo:** proyecto histórico (`consulting_project_reference`).  
**Producción:** en operación (`in_production`).  
**Versión documental:** 1.1.0.

## Organización y operación

- **Organización:** Inter Miami CF.
- **Ubicación:** Miami, Florida, Estados Unidos.
- **Actividad/contexto:** Inter Miami CF opera un club de fútbol profesional. El expediente histórico documenta una tienda digital para uniformes, ropa, accesorios y colecciones oficiales; el expediente as-built disponible no registra las condiciones de licencia y fulfillment.
- **Equipo previsto:** 18 personas estimadas: comercio digital (4), catálogo y merchandising (4), marketing (3), atención al cliente (4), operaciones e inventario (3).
- **Usuarios y carga:** 20.000 sesiones/día en operación habitual; hasta 100.000 sesiones en día de lanzamiento o partido de alta demanda; pico de diseño de 4.000 sesiones simultáneas. Volumen esperado: 900 órdenes/día habitual y hasta 5.000 en campaña. Cifras de contexto de este expediente; no equivalen a telemetría histórica y su fuente/fecha no están registradas.

## Objetivo

Permitir descubrir productos, revisar disponibilidad y completar compras seguras desde web y móvil, con catálogo y estado de órdenes integrados a los sistemas comerciales.

## Requisitos funcionales

- Catálogo por producto, talla, jugador y colección, con imágenes optimizadas.
- Carrito y checkout integrado con un proveedor de pagos certificado; no almacenar números de tarjeta.
- Consulta de inventario y registro de órdenes con proveedor de fulfillment/envíos.
- Gestión de cuentas, atención, devoluciones y notificaciones según políticas aprobadas.

## Alcance de solución

| Componente | Responsabilidad y estado | Motivo | Baseline/perfil documentado |
|---|---|---|---|
| Amazon CloudFront + Amazon S3 | Distribuye el frontend e imágenes; S3 usa acceso de origen controlado. CDN/OAC no están en el Terraform del catálogo. | Entregar contenido de tienda y activos de merchandising con caché y bucket privado. | S3 `private_versioned_365d`; CloudFront/OAC no están representados en los módulos actuales. |
| Amazon API Gateway HTTP API + AWS Lambda | API para catálogo y órdenes; función y rol desplegados no descritos en este snapshot. | Separar la interfaz pública de la lógica de negocio y las integraciones. | API `throttling_500rps_burst_1000`; Lambda no está en el baseline. |
| Amazon DynamoDB | Referencia para catálogo, carrito y órdenes; modelo desplegado no registrado. | Acceso de baja latencia y persistencia administrada para las operaciones de tienda. | `aws-dynamodb-single-table` / `on_demand`; claves e índices as-built no registrados. |
| Proveedor de pagos, inventario y fulfillment | Integraciones externas; contratos y servicios reales no registrados aquí. | Delegar procesamiento de pago y enlazar disponibilidad/envío con sistemas de negocio. | Fuera de los baselines y Terraform de este catálogo. |

### Flujo principal

1. Cliente → CloudFront → frontend y contenido desde S3 privado.
2. Navegador → API Gateway → Lambda → catálogo/carrito/órdenes en DynamoDB.
3. Checkout → proveedor de pagos externo; guardar únicamente referencias y estados.
4. Lambda integra inventario, envíos y notificaciones mediante APIs autorizadas.

## Alcance de esta referencia documental

La composición Terraform 1.1.0 del catálogo modela únicamente API Gateway HTTP API, un bucket S3 privado y una tabla DynamoDB. No es un export del entorno histórico completo; frontend/CDN, funciones Lambda, identidad, integraciones y red no están representados aquí. Consultar inventario as-built antes de usarla para reproducir o modificar producción.

## Requisitos de calidad y datos por recuperar

El expediente as-built disponible no registra licencia, sistema de catálogo/inventario, requisitos PCI, consentimiento, protección contra abuso, WAF, identidad, retención, RTO/RPO ni costos medidos.

Recuperar del expediente operativo las cargas medidas, presupuesto, región, controles de privacidad/seguridad, continuidad y responsables. Las cifras de equipo y tráfico aquí incluidas son contexto de planeación y no mediciones confirmadas.

## Fuentes de contexto

- [Inter Miami CF](https://www.intermiamicf.com/) — sitio oficial de la organización.
