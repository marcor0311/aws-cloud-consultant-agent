# Plan maestro — Agente 4 Cloud FinOps (issue #20)

## Objetivo y límites

El agente 4 consume una revisión de arquitectura aprobada, prepara entradas para
AWS Pricing Calculator, conserva la evidencia obtenida por Codex, analiza los
resultados frente al presupuesto y produce entregables verificables. No modifica
la arquitectura, no inventa precios o consumos y no despliega infraestructura.

Codex es el orquestador entre los MCP de Arquitectura y FinOps. Los servidores no
se llaman directamente: Codex transporta sin reinterpretar el handoff aprobado,
opera el navegador y devuelve a FinOps la evidencia estructurada de la
calculadora.

## Decisiones obligatorias

1. Se consumen `ArchitectureFinOpsHandoff`, `EconomicContract` y
   `FinOpsHandoffAcceptance` del agente 3; no se crean copias FinOps.
2. Se reutilizan `WorkflowStore`, revisión, SHA-256 e idempotencia compartidos.
3. La aceptación de recepción del handoff es independiente de
   `FinOpsEvaluationDecision`.
4. Los estados operativos FinOps son distintos del resultado presupuestario:
   `within_budget` nunca significa por sí mismo `approved`.
5. Una aprobación económica exige la autorización humana y la referencia que
   establezcan las reglas del proyecto, incluso si el costo está dentro del
   presupuesto.
6. AWS Pricing Calculator es la fuente principal para servicios compatibles;
   los cálculos propios se limitan a derivados trazables y usan `Decimal`.
7. Codex opera un navegador real y conserva evidencia. Esta capacidad no se
   considera validada hasta la prueba real del Bloque C, inicialmente con S3 y
   parámetros conocidos.
8. La política de cercanía al presupuesto será configurable; no se inventarán
   umbrales.
9. Las correcciones arquitectónicas reutilizarán `FinOpsCorrectionRequest` y
   regresarán al agente 3 por medio de Codex, sin mutar revisiones aprobadas.
10. El agente 4 no se considerará completo hasta demostrar calculadora real,
    MCP, trazabilidad al SHA aprobado y publicación de los entregables.

## Bloque A — Contrato de entrada y validación FinOps

**Objetivo:** consumir el handoff existente y registrar una recepción idempotente
sin reconstruir infraestructura compartida.

**Alcance:** modelos propios solo para estado operativo y decisión de evaluación;
adaptador de entrada; validación del handoff listo, revisión, SHA, asignación y
persistencia existentes. No incluye precios ni workflow LangGraph FinOps.

**Archivos:** `app/finops/`, pruebas específicas en `tests/finops_agent/` y este
plan. El agente 3 solo se modifica ante una incompatibilidad demostrada.

**Aceptación:** un handoff listo y persistido se recibe una sola vez; uno
bloqueado, alterado, inexistente o dirigido a otra revisión se rechaza; reiniciar
el adaptador conserva el registro; el recibo usa `FinOpsHandoffAcceptance`; una
decisión `within_budget` no se transforma automáticamente en aprobación.

**Pruebas mínimas:** recepción válida, integridad SHA, rechazo de bloqueos,
idempotencia/reinicio y separación entre recepción, resultado y autorización.

## Bloque B — Preparación de estimaciones AWS

**Objetivo:** transformar cada `PricingInputV1_1` en instrucciones tipadas para
AWS Pricing Calculator sin asignar precios.

**Alcance:** mapeos por servicio, comenzando con S3; unidades, región,
configuración, consumos conocidos, limitaciones y valores faltantes. Una dimensión
no representable queda explícitamente bloqueada.

**Archivos previstos:** adaptadores de calculadora bajo `app/finops/` y pruebas
con payloads aprobados del agente 3.

**Aceptación:** cada entrada conserva recurso, dimensión, procedencia y unidad;
no aparecen valores por defecto inventados; S3 produce pasos reproducibles.

**Pruebas mínimas:** S3 completo, cantidad desconocida, dimensión no soportada y
trazabilidad uno a uno.

**Estado:** implementado para S3. Los demás servicios conservan todos sus datos y
producen bloqueos explícitos por dimensión hasta incorporar un adaptador validado;
no se generan precios, conversiones ni selectores de interfaz en este bloque.

## Bloque C — Automatización real de AWS Pricing Calculator

**Objetivo:** demostrar que Codex introduce una configuración S3 conocida en la
calculadora oficial y recupera resultados verificables.

**Alcance:** navegador real visible o inspeccionable, captura de parámetros,
fecha, región, resultados y enlace/exportación cuando esté disponible. Una prueba
simulada no satisface este bloque.

**Aceptación:** la evidencia permite comparar la entrada preparada con la UI y el
resultado; fallos o cambios de la interfaz se reportan, no se sustituyen por un
precio inventado.

**Pruebas mínimas:** recorrido real S3 y una entrada inválida o incompleta.

**Estado:** validado el 9 de noviembre de 2026 mediante una sesión aislada del
navegador integrado de Codex. AWS Pricing Calculator confirmó S3 Standard en
`us-east-1` con 100 GB/mes, 100 000 solicitudes GET/mes y 10 GB/mes a Internet.
La evidencia oficial exportada y su contrato tipado están en
`docs/evidence/agent4/block-c-s3/`.

## Bloque D — Análisis económico y presupuestario

**Objetivo:** interpretar resultados verificados y calcular indicadores
derivados.

**Alcance:** mensual/anual, desglose, porcentaje, diferencia presupuestaria,
incertidumbre, escenarios y recomendaciones. La política de alerta será explícita
y configurable.

**Aceptación:** todos los importes usan `Decimal`; cada total referencia evidencia;
`within_budget`, `near_limit`, `over_budget` y `not_evaluable` permanecen
separados de la decisión autorizada.

**Pruebas mínimas:** totales, redondeo, presupuesto mensual/anual, información
faltante y aprobación excepcional debidamente autorizada.

## Bloque E — MCP FinOps y correcciones

**Objetivo:** exponer las operaciones FinOps y coordinar los MCP mediante Codex.

**Alcance:** recibir handoff, preparar calculadora, registrar evidencia, consultar
evaluación, decidir y emitir la corrección ya tipada por Arquitectura. No incluye
un cliente MCP agente-a-agente.

**Aceptación:** `tools/list` y llamadas MCP reales; el recibo exacto vuelve al MCP
de Arquitectura; una corrección conserva revisión, SHA y referencias.

**Pruebas mínimas:** recorrido MCP feliz, duplicado, evidencia incorrecta y ciclo
de corrección.

## Bloque F — Persistencia y entregables

**Objetivo:** producir un historial inmutable y artefactos versionados en
`docs/04-finops/`.

**Alcance:** estimación, evidencia, análisis, escenarios, riesgos,
recomendaciones, manifiesto y `forecast.xlsx`. El Excel tendrá fórmulas, escenarios
y referencias trazables a las estimaciones verificadas; no contendrá precios
manuales sin procedencia.

**Aceptación:** publicación idempotente por revisión/SHA; manifiesto verificable;
`forecast.xlsx` recalcula mensual y anual y enlaza cada fila con su evidencia.

**Pruebas mínimas:** reinicio, duplicado, cambio de contenido, manifiesto y
validación programática de fórmulas/referencias del libro.

## Bloque G — Integración y evidencia final

**Objetivo:** probar el flujo completo Arquitectura → Codex → FinOps → Codex →
Arquitectura/Ingeniería y reunir evidencia académica.

**Alcance:** calculadora real, ambos MCP, GitHub MCP, CI, PostgreSQL cuando el
entorno aislado esté disponible, regresión afectada y documentación final.

**Aceptación:** una revisión aprobada produce costos trazables y decisión humana;
los ajustes generan una nueva revisión; la entrega a Ingeniería solo ocurre tras
la autorización y publicación requeridas.

**Pruebas mínimas:** recorrido completo exitoso, devolución a Arquitectura,
reinicio/idempotencia y fallos de servicios externos claramente clasificados.

## Estado inicial

El Bloque A puede ejecutarse sin navegador ni precios. Los Bloques B y C son la
siguiente dependencia: B prepara una entrada S3 determinista y C demuestra la
operación real. GitHub, PostgreSQL y la regresión integral se reservan para los
bloques que los requieren.
