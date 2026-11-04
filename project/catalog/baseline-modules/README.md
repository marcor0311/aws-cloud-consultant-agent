# Módulos de línea base

Módulos Terraform organizados por proveedor y recurso.

```text
baseline-modules/
└── aws/
    ├── api-gateway/
    ├── dynamodb/
    └── s3/
```

| Recurso | Perfiles |
| --- | --- |
| [API Gateway](aws/api-gateway/PROFILES.md) | HTTP API con límites de solicitudes y ráfagas. |
| [DynamoDB](aws/dynamodb/PROFILES.md) | Tabla con capacidad bajo demanda o aprovisionada. |
| [S3](aws/s3/PROFILES.md) | Bucket privado con opciones de versionado y retención. |

Cada recurso incluye `module.yaml`, versiones `1.0.0` y `1.1.0`, documentación y ejemplos ejecutables en `examples/profiles/`. Los perfiles fijan una versión del módulo; representan configuraciones, no releases.

Los módulos conservan su estado de borrador. Antes de usarlos en producción, validar configuración, seguridad, políticas y costos, y registrar la aprobación. Los ejemplos no incluyen credenciales ni backend de estado corporativo.
