# Terraform composition | 1.0.0

**Estado:** snapshot documental reemplazado por 1.1.0. Esta composición inicial referencia los módulos baseline 1.0.0 y se conserva para historial; no se recomienda para nuevos entornos.

La composición crea únicamente API Gateway HTTP API, un bucket S3 privado y una tabla DynamoDB. Lambda, frontend/CDN, identidad, integraciones de negocio y demás componentes de los diagramas quedan fuera de esta revisión.

Para la configuración vigente, consulte `../1.1.0/terraform/README.md`. Esta carpeta no autoriza `terraform apply`.
