# Ficha de proyecto | Sitio de exhibición de vehículos y captación de clientes para Mercedes-Benz Canada

**Tipo:** proyecto histórico (`consulting_project_reference`).  
**Producción:** en operación (`in_production`).  
**Versión documental:** 1.1.0.

## Organización y operación

- **Organización:** Mercedes-Benz Canada.
- **Ubicación:** Mississauga, Ontario, Canadá.
- **Actividad:** comercialización y soporte de vehículos Mercedes-Benz en Canadá, en coordinación con su red de concesionarios.
- **Equipo de operación:** 18 personas: marketing y contenido (5), coordinación de concesionarios (4), ventas y atención digital (5) y producto y tecnología (4).
- **Usuarios y capacidad:** el sitio atiende 7.000 sesiones diarias en operación habitual y dispone de capacidad para 25.000 sesiones por día y 1.500 sesiones simultáneas durante lanzamientos y campañas. Procesa hasta 350 formularios de interés diarios en jornadas de campaña.

La consultoría implementó el canal digital de exhibición de vehículos y contacto comercial de Mercedes-Benz Canada. El sitio está en producción y reúne modelos, especificaciones, galerías, historia de la empresa y contenido de marca. La información se integra con el catálogo maestro y el sistema corporativo de contenidos; las solicitudes comerciales se transfieren al CRM y al concesionario correspondiente.

## Objetivo

Facilitar que los clientes exploren la gama Mercedes-Benz, comparen vehículos y contacten al concesionario adecuado, convirtiendo el interés digital en solicitudes comerciales atendidas por la red de ventas.

## Requisitos funcionales

- Explorar el catálogo de vehículos, consultar especificaciones y galerías y comparar modelos.
- Consultar historia, noticias, sostenibilidad y campañas de Mercedes-Benz Canada.
- Localizar concesionarios y solicitar información, cotizaciones y pruebas de manejo.
- Transferir las solicitudes al CRM corporativo con una referencia de seguimiento.
- Publicar información del catálogo maestro y del sistema corporativo de contenidos sin duplicar su administración.
- Ofrecer una experiencia accesible en inglés y francés desde computadoras y dispositivos móviles.

## Alcance de solución

| Componente | Responsabilidad en producción | Motivo de selección | Configuración de referencia |
|---|---|---|---|
| Amazon CloudFront | Distribuye el sitio, las fotografías y las galerías de vehículos mediante caché. | Mantiene una navegación ágil para visitantes de distintas zonas de Canadá. | Distribución con acceso de origen controlado a S3. |
| Amazon S3 | Almacena la interfaz web y los archivos publicados por el equipo de contenido. | Proporciona almacenamiento privado y versionado para material visual y editorial. | `private_versioned_90d`. |
| Amazon API Gateway HTTP API | Expone las consultas del catálogo y la recepción de formularios comerciales. | Centraliza el acceso a las integraciones y controla las solicitudes a la API. | `throttling_100rps_burst_200`: 100 solicitudes por segundo y ráfagas de 200. |
| AWS Lambda | Procesa búsquedas, valida formularios y coordina la transferencia de solicitudes al CRM. | Separa la presentación del sitio de las reglas de negocio y los sistemas corporativos. | Funciones por operación con permisos limitados a sus integraciones. |
| Amazon DynamoDB | Conserva el registro temporal y el estado de transferencia de las solicitudes comerciales. | Evita perder o duplicar solicitudes durante reintentos de comunicación con el CRM. | `aws-dynamodb-single-table` / `on_demand`, con identificadores idempotentes. |
| Catálogo maestro, sistema de contenidos, CRM y concesionarios | Administran vehículos, publicaciones y atención comercial. | Conservan las fuentes corporativas de información y la asignación de clientes a la red de ventas. | Integraciones mediante APIs autorizadas. |

### Flujo principal

1. El visitante accede al sitio; CloudFront entrega la interfaz, fotografías y contenido desde S3 privado.
2. La interfaz consulta la API para recuperar información de los modelos desde el catálogo maestro.
3. El visitante compara vehículos, consulta la marca y selecciona un concesionario o completa un formulario de interés.
4. Lambda valida la solicitud y registra su identificador y estado de transferencia en DynamoDB.
5. La integración entrega la solicitud al CRM y al concesionario correspondiente; el visitante recibe una confirmación con su referencia.
6. El equipo editorial publica contenido aprobado desde el sistema corporativo de contenidos.

## Operación en producción

Marketing y contenido mantienen las páginas de marca, galerías y campañas. La coordinación de concesionarios administra las rutas de atención comercial; ventas y atención digital dan seguimiento a las solicitudes; producto y tecnología mantienen las integraciones y la experiencia del sitio.

El catálogo maestro conserva las especificaciones de los vehículos y el CRM mantiene la relación comercial con el cliente. DynamoDB registra los estados de transferencia para controlar reintentos y evitar duplicados. La publicación utiliza contenido versionado en S3, mientras CloudFront mantiene su distribución. El equipo supervisa errores de formularios y solicitudes pendientes de entrega al CRM.

## Requisitos de calidad

- Navegación accesible y adaptable a computadoras y dispositivos móviles, con contenido en inglés y francés.
- Coherencia entre las especificaciones publicadas y el catálogo maestro corporativo.
- Tratamiento de datos de contacto y consentimiento conforme a las políticas de privacidad de la operación canadiense.
- Transferencia de formularios con seguimiento, control de duplicados y reintentos ante errores de integración.
- Almacenamiento privado, permisos mínimos y recuperación de versiones del contenido editorial.

## Fuentes de contexto

- [Mercedes-Benz Group — ubicación en Canadá](https://group.mercedes-benz.com/careers/about-us/locations/location-detail-page-5136.html) — contexto corporativo y ubicación de la organización.
