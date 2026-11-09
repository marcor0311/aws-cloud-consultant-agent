# 6. Project Closure Agent

**Responsabilidad:** Informe ejecutivo y cierre.

Trabaja con el Engagement Manager. Recibe la entrega técnica, costos, decisiones,
evidencias y mediciones del proceso; consolida el informe ejecutivo en PDF. El
flujo previsto permite solicitar ajustes, aprobar el informe, presentarlo a
dirección y registrar el cierre del proyecto.

## Estado

Existe un avance determinista en el nodo `executive_report_agent` de
[delivery/workflow.py](../../backend/app/delivery/workflow.py), con renderizado en
[delivery_pdf.py](../../backend/app/integrations/delivery_pdf.py). Genera un PDF
borrador desde la entrega de ingeniería y datos simulados, con métricas y
respaldos persistidos. Su código permanece en el backend.

Todavía faltan el acceso específico por MCP, las entradas reales del proceso,
ajustes, aprobación humana y cierre. Generar el borrador no cierra el proyecto.
Ver [entrega 1](../../../docs/delivery-1.md).

Contrato funcional: [issues.md](../../../issues.md#6-engagement-manager--informe-ejecutivo).
La numeración identifica al agente dentro del registro; no es un paquete Python.
