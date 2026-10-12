# Composición Terraform | 1.1.0

**Estado:** composición de referencia del catálogo; el proyecto histórico está en producción, pero este Terraform no está verificado como el código desplegado. Usa baselines locales versionados: API Gateway HTTP API 1.1.0, private S3 1.1.0, DynamoDB single-table 1.1.0.

## Recursos representados en el snapshot

- HTTP API, Lambda integration/permission, stage throttling and access logs.
- Private S3 bucket, TLS-only policy, encryption, object versioning and noncurrent-version lifecycle.
- DynamoDB table with deletion protection, encryption and point-in-time recovery.

## Dependencias fuera de esta composición

Lambda code/role, application and CDN, customer identity, networking, organization-wide state backend, payments/CRM/inventory/ticketing, KMS keys/policies if customer-managed keys are required, budgets, alarms and operational ownership. Confirmar el perfil elegido y cada override en `audit-record.yaml`.

## Uso de esta referencia

No ejecutar `apply` contra el entorno histórico ni presentar este código como export as-built. Antes de reutilizarlo, contrastar recursos, variables, estado, versiones y controles con el inventario desplegado. `.tfvars.example` contiene valores ilustrativos.
