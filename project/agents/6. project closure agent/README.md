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

El MCP de `app.delivery.mcp` también genera un informe por expediente sin ejecutar
ingeniería, con entrada técnica opcional. `intake_id` selecciona una recepción de
#21, con corridas, comprobaciones, versiones y archivos verificados por hash. El
PDF muestra retrabajo explícito y resultados parciales/fallidos sin aprobarlos.
Lee fuentes y mediciones existentes del
workflow, conserva una instantánea con hash, permite corregir secciones, versionar
y aprobar el PDF parcial. El operador debe corresponder al responsable registrado.
Los informes parciales no cierran el expediente; faltan la integración de las
entregas reales de Arquitectura/FinOps/Ingeniería y el cierre del proceso principal.
Ver [revisión, métricas y límites](../../../docs/revision-informe-ejecutivo.md).

Contrato funcional: [issues.md](../../../issues.md#6-engagement-manager--informe-ejecutivo).
La numeración identifica al agente dentro del registro; no es un paquete Python.
