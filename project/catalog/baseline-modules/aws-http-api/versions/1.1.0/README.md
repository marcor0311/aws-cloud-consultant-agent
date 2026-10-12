# aws-http-api 1.1.0

Creates an API Gateway HTTP API, default route/stage, Lambda proxy integration, invoke permission, access log group, and stage throttling.

Status: draft; not approved for production. Profiles are runnable root-module examples in [`examples/profiles`](../../examples/profiles/). They use exact module inputs and pin this snapshot.

## Inputs

| Input | Required/default | Purpose |
|---|---|---|
| `name` | required | API name |
| `lambda_function_name`, `lambda_invoke_arn` | required | Existing Lambda integration target |
| `access_log_retention_days` | 30 | Supported CloudWatch Logs retention period |
| `throttling_rate_limit` | 50 | Sustained stage request rate; confirm quotas and backend capacity |
| `throttling_burst_limit` | 100 | Stage burst limit |
| `tags` | `{}` | Resource tags |

Custom domains, WAF association, authorizers, routes, and custom access-log formats are outside this snapshot. Add and review the required capability before production approval.


## Límites antes de adoptar

Los límites de throttling no garantizan capacidad: confirma cuotas regionales/cuenta, concurrencia Lambda y comportamiento del backend. WAF, autorización, dominios personalizados, cuotas por cliente y rutas explícitas requieren decisiones y capacidades adicionales antes de aprobar una API pública.
