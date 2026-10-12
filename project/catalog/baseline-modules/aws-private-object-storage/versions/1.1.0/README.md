# aws-private-object-storage 1.1.0

Creates a private S3 bucket with public-access blocking, bucket-owner-enforced ownership, encryption, versioning controls, optional noncurrent-version expiration, optional CORS, and an explicit policy denying insecure transport.

Status: draft; not approved for production. Profiles are runnable root-module examples in [`examples/profiles`](../../examples/profiles/). They use exact module inputs and pin this snapshot.

## Inputs

| Input | Required/default | Purpose |
|---|---|---|
| `bucket_name` | required | Globally unique bucket name |
| `versioning_enabled` | true | Enables object versioning |
| `noncurrent_version_expiration_days` | null | Positive whole-number retention for noncurrent versions |
| `cors_allowed_origins` | `[]` | Exact browser origins; empty disables CORS |
| `kms_key_arn` | null | Optional customer-managed key; null uses SSE-S3 |
| `tags` | `{}` | Resource tags |

The module owns the bucket policy to enforce TLS. If another policy is required, merge reviewed statements into this module before use; do not create a competing `aws_s3_bucket_policy` for the same bucket. Confirm retention, KMS key policy, access logging, replication, and recovery requirements for the workload.


## Límites antes de adoptar

La expiración afecta versiones no actuales, no objetos actuales. El módulo no configura replicación, acceso de logging, retención legal, clasificación de datos ni política de ciclo de vida para objetos actuales. Añade los controles que exija el caso antes de aprobar su uso.
