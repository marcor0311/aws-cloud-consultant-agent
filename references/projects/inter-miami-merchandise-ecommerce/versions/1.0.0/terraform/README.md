> **Referencia ficticia académica.** Las empresas conservan sus nombres del catálogo original; las afirmaciones de producción, capacidad y resultados describen un escenario ficticio, no una relación comercial verificada. El código Terraform histórico no se recupera en esta copia documental.

# Terraform composition | 1.0.0

**Estado:** snapshot documental reemplazado por 1.1.0. Esta composición inicial referencia los módulos baseline 1.0.0 y se conserva para historial; no se recomienda para nuevos entornos.

La composición crea únicamente API Gateway HTTP API, un bucket S3 privado y una tabla DynamoDB. Lambda, frontend/CDN, identidad, integraciones de negocio y demás componentes de los diagramas quedan fuera de esta revisión.

Para la configuración vigente, consulte `../1.1.0/terraform/README.md`. Esta carpeta no autoriza `terraform apply`.
