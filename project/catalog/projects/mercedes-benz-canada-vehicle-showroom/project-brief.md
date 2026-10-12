# Ficha de proyecto | Sitio de exhibición de vehículos y captación de clientes para Mercedes-Benz Canada

**Tipo:** proyecto histórico (`consulting_project_reference`).  
**Producción:** en operación (`in_production`).  
**Versión documental:** 1.1.0.

## Organización y operación

- **Organización:** Mercedes-Benz Canada.
- **Ubicación:** Mississauga, Ontario, Canadá.
- **Actividad/contexto:** Mercedes-Benz Canada comercializa y da soporte a vehículos Mercedes-Benz en Canadá. El proyecto histórico comprende un sitio de descubrimiento de vehículos y derivación de prospectos, conectado al catálogo maestro, CMS, CRM y concesionarios existentes.
- **Equipo previsto:** 18 personas estimadas para el producto digital: marketing y contenido (5), coordinación de concesionarios (4), ventas/atención digital (5), producto/tecnología (4).
- **Usuarios y carga:** 7.000 sesiones/día en operación habitual; hasta 25.000 durante lanzamientos/campañas; pico de diseño de 1.500 sesiones simultáneas y hasta 350 formularios de interés/día de campaña. Cifras de contexto de este expediente; no equivalen a telemetría histórica y su fuente/fecha no están registradas.

## Objetivo

Presentar la gama de vehículos, sus especificaciones y contenido de marca; dirigir al cliente potencial al concesionario adecuado y transferir solicitudes al CRM corporativo.

## Requisitos funcionales

- Catálogo con especificaciones, galerías y comparador de modelos.
- Contenido corporativo, historia, noticias, sostenibilidad y campañas.
- Localizador de concesionarios y formularios de información, cotización o prueba de manejo.
- Integración con catálogo maestro, CMS y CRM; no crear fuentes paralelas de datos.
- Experiencia bilingüe inglés/francés y accesible, sujeta a validación legal y editorial.

## Alcance de solución

| Componente | Responsabilidad y estado | Motivo | Baseline/perfil documentado |
|---|---|---|---|
| Amazon CloudFront + Amazon S3 | Distribuye el sitio y galerías desde almacenamiento privado; CDN no incluida en el Terraform del catálogo. | Servir contenido visual de vehículos con caché y separar publicación de contenido de la API. | S3 `private_versioned_90d`; CloudFront no está representado en los módulos actuales. |
| Amazon API Gateway HTTP API + AWS Lambda | Búsqueda de catálogo y envío de leads; implementación Lambda y rol no descritos en el snapshot. | Exponer interfaces controladas para catálogo y formularios sin duplicar sistemas de registro. | API `throttling_100rps_burst_200`; Lambda no está en el baseline. |
| Amazon DynamoDB | Persistencia idempotente/temporal solo si el CRM no ofrece interfaz durable; uso desplegado no registrado. | Evitar pérdida o duplicación de solicitudes durante transferencia al CRM, si la implementación histórica lo requería. | `aws-dynamodb-single-table` / `on_demand`; necesidad y modelo as-built no registrados. |
| Catálogo maestro, CMS, CRM y red de concesionarios | Sistemas externos y fuentes de registro; interfaces históricas no descritas aquí. | Reutilizar datos de vehículos, contenido y asignación de prospectos corporativos. | Integraciones fuera de los baselines y Terraform de este catálogo. |

### Flujo principal

1. Cliente → CloudFront → sitio, contenido e imágenes.
2. Sitio → API Gateway/Lambda → catálogo maestro para especificaciones vigentes.
3. Formulario → API Gateway/Lambda → CRM o sistema del concesionario; devolver confirmación y referencia.
4. CMS corporativo → publicación de contenido aprobada al sitio.

## Alcance de esta referencia documental

La composición Terraform 1.1.0 del catálogo modela únicamente API Gateway HTTP API, un bucket S3 privado y una tabla DynamoDB. No es un export del entorno histórico completo; frontend/CDN, funciones Lambda, identidad, integraciones y red no están representados aquí. Consultar inventario as-built antes de usarla para reproducir o modificar producción.

## Requisitos de calidad y datos por recuperar

El expediente as-built disponible no registra contratos/API de CRM y catálogo, consentimiento/retención de leads, residencia y privacidad en Canadá, accesibilidad, identidad, WAF, SLA, RTO/RPO ni presupuesto medido.

Recuperar del expediente operativo las cargas medidas, presupuesto, región, controles de privacidad/seguridad, continuidad y responsables. Las cifras de equipo y tráfico aquí incluidas son contexto de planeación y no mediciones confirmadas.

## Fuentes de contexto

- [Mercedes-Benz Group — ubicación en Canadá](https://group.mercedes-benz.com/careers/about-us/locations/location-detail-page-5136.html) — fuente corporativa de ubicación.
