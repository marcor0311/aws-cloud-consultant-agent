# aws-dynamodb-single-table 1.1.0

A DynamoDB single-table baseline with fixed string keys (`pk`, `sk`), point-in-time recovery, deletion protection, encryption, optional TTL, and PAY_PER_REQUEST or static PROVISIONED capacity.

Status: draft; not approved for production. Profiles are runnable root-module examples in [`examples/profiles`](../../examples/profiles/). They use the exact module inputs and pin this snapshot.

## Inputs

| Input | Required/default | Purpose |
|---|---|---|
| `table_name` | required | Table name |
| `billing_mode` | `PAY_PER_REQUEST` | Billing/capacity mode |
| `read_capacity`, `write_capacity` | null | Positive whole-number RCU/WCU for `PROVISIONED` |
| `deletion_protection_enabled` | true | Blocks accidental table deletion |
| `ttl_attribute_name` | null | Enables TTL for the named data-model attribute |
| `kms_key_arn` | null | Optional customer-managed encryption key |
| `tags` | `{}` | Resource tags |

The table exposes only `pk` and `sk` as key attributes and does not yet model GSIs, autoscaling, streams, or replicas. Confirm access patterns and regional recovery needs before selecting it. If a workload requires an unsupported feature, extend and release the module before approval; do not silently fork the example. Provisioned capacity is static and must be sized from measurements.


## Límites antes de adoptar

Este módulo no configura autoscaling, GSI/LSI, streams ni réplicas globales; sus dos claves son `pk` y `sk`. Elige `PAY_PER_REQUEST` para cargas variables/no medidas o dimensiona `PROVISIONED` con mediciones. Si el patrón necesita una capacidad no cubierta, amplía la interfaz y publica una nueva versión antes de aprobar el diseño.
