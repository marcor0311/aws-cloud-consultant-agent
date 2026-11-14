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

Todavía faltan las entradas reales de Arquitectura y FinOps, validaciones
Terraform y seguridad, despliegue local y el ciclo de PR/revisión. El recorrido
es separado del proceso principal. Ver [entrega 1](../../../docs/delivery-1.md).

Contrato funcional: [issues.md](../../../issues.md#5-cloud-infrastructure-engineer--implementación).
La numeración identifica al agente dentro del registro; no es un paquete Python.
