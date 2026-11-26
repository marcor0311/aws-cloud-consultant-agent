# 5. Terraform Agent

**Responsabilidad:** Implementación y validación local.

Trabaja con el Cloud Infrastructure Engineer en el mismo repositorio del
proyecto. Recibe arquitectura y costos aprobados; reutiliza baselines versionados,
implementa Terraform y prepara pruebas, validaciones de seguridad, evidencias
locales y un PR para revisión y aprobación del arquitecto.

## Estado

Existe un avance determinista en el nodo `engineering_agent` de
[delivery/workflow.py](../../backend/app/delivery/workflow.py). Valida coherencia
de insumos simulados, prepara archivos Terraform S3 y persiste la entrega en
PostgreSQL. Su código permanece en el backend y esta carpeta no lo duplica.

El runner de AWS Emulator ya permite el ciclo Terraform, seguridad, políticas y
limpieza para S3/KMS; conserva su alcance de demostración. Ver
[validación existente](../../../docs/validacion-aws-emulator.md).

El incremento de recepción en `app/delivery/engineering.py` recibe paquetes
versionados, contrasta decisiones registradas de Arquitectura/FinOps y conserva
archivos y hashes. Importa evidencias por corrida y commit, con resultados,
versiones e intervalos técnicos en PostgreSQL. CLI y MCP privados permiten
consultar esos recibos y descargar sus respaldos; no ejecutan infraestructura.
Las métricas del expediente y del informe incluyen esos intervalos, sin duplicar
el trabajo paralelo y manteniendo la procedencia declarada de los resultados.
Ver [entrada, evidencias y métricas](../../../docs/engineering-intake.md).

Existe un catálogo por recepción con revisión/hash, combinaciones, fallos y límites
de las corridas importadas. La entrega técnica definitiva contrasta su revisión,
hash y arquitecto con la aprobación de etapa 5, exige corridas local/CI exitosas y
conserva referencias de PR, merge, protección de rama y baselines confirmadas por
el operador. Emite disponibilidad en SQL para #22; no autentica GitHub remotamente.

Faltan el acuerdo del contrato con Arquitectura/FinOps y el piloto con sus insumos
reales, la automatización de verificación externa y del ciclo
PR/revisión/merge/notificación externa.
Recibir o importar una corrida exitosa no equivale a aprobación del arquitecto.

Contrato funcional: [issues.md](../../../issues.md#5-cloud-infrastructure-engineer--implementación).
La numeración identifica al agente dentro del registro; no es un paquete Python.
