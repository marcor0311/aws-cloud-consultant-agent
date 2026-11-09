# 4. FinOps Agent

**Responsabilidad:** Validación de costos.

Trabaja con el FinOps Analyst desde un cliente MCP. Recibe la arquitectura
aprobada, recursos, región, supuestos y presupuesto. Debe generar la estimación
de AWS Pricing Calculator y el Excel de costos, validar coherencia y presupuesto
y, tras la aprobación humana, entregar ambos insumos a Ingeniería. Si requiere
ajustes, devuelve el trabajo a Arquitectura con referencias a la revisión.

## Estado

Carpeta de organización; todavía no tiene runtime propio. Los contratos de la
etapa están en [workflow](../../backend/app/workflow/). Las herramientas de
calculadora, Excel y publicación de costos por MCP siguen pendientes. Los costos
de la entrega 1 son simulados y no constituyen una implementación de este agente.

Contrato funcional: [issues.md](../../../issues.md#4-finops-analyst--costos).
La numeración identifica al agente dentro del registro; no es un paquete Python.
