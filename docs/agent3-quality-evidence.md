# Cloud Architecture Agent — calidad y evidencia

Este documento registra evidencia verificable del issue #19. Distingue pruebas
automatizadas, integraciones locales y actividades remotas que aún no se han
ejecutado. Un contrato o mock no se presenta como evidencia de una operación
real en GitHub, PostgreSQL, AWS o el MCP de FinOps.

## Controles automatizados

El job `architecture-agent` de `.github/workflows/checks.yml`:

1. Usa Python 3.12 y PostgreSQL 16 desechable.
2. Descarga el repositorio del agente, los módulos baseline y la entrega Nike del
   agente 2 como repositorios hermanos.
3. Ejecuta Ruff sobre la aplicación y las pruebas del agente 3.
4. Ejecuta todas las pruebas de `tests/architecture_agent/`, incluidas las
   integraciones con el proceso principal y el retrabajo FinOps.
5. Proporciona `WORKFLOW_TEST_POSTGRES_URL`, por lo que la prueba PostgreSQL no
   queda omitida en CI.
6. Instala `awsdac v0.24`, verifica su SHA-256 y renderiza realmente el YAML
   generado. El render requiere acceso de salida a la definición oficial fijada
   al tag `v0.24` en `raw.githubusercontent.com`; un fallo de esa dependencia
   externa hace fallar el job y no se sustituye por un PNG simulado.

La suite valida contratos Pydantic, LangGraph con interrupción humana,
persistencia y recuperación, revisiones inmutables, retrabajo FinOps, artefactos,
diagramas, políticas, manifiestos, hashes, GitHub receipts, métricas y handoffs.

## Matriz del issue #19

| Criterio documentado | Estado | Evidencia disponible | Pendiente real |
| --- | --- | --- | --- |
| Consumir la entrega aprobada del agente 2 | Implementado y probado localmente | `test_project_repository.py`, contrato 1.2 y repo Nike fijado a commit | Demostración MCP conservada como evidencia de sesión |
| Proponer recursos, región, dependencias y módulos | Implementado | `ArchitecturePackage`, catálogo baseline y pruebas de contrato | Validar mediante una conversación MCP evaluada por el arquitecto |
| Diagrama AWS como código | Implementado localmente | YAML AWS DAC, PNG, Mermaid y `test_diagram_artifacts.py` | Publicar el PNG mediante PR real |
| ADRs, seguridad y políticas como código | Implementado y validado | Artefactos derivados de una revisión y política JSON validada | Revisión humana del contenido del caso real |
| Entradas económicas para FinOps | Implementado | Contrato económico tipado, unidades y procedencia | Consumo real por el MCP del agente 4 |
| Revisión humana exacta | Implementado | Interrupción LangGraph, revisión y SHA-256 | Evidencia remota de aprobación del PR |
| Publicación GitHub y PR | Frontera local implementada | Plan y receipts tipados, hashes e idempotencia | Ejecutar GitHub MCP conectado y registrar PR/merge reales |
| Corrección FinOps → Arquitectura | Implementado | Ciclo revisión 1 → corrección → revisión 2 | Integración con el MCP real de FinOps |
| PostgreSQL y recuperación | Implementado; CI preparado | Prueba opcional local y servicio PostgreSQL del job | Obtener la primera ejecución verde del job remoto |
| Métricas académicas | Implementado | Lead Time, Process Time, espera y retrabajo consultables | Conservar resultados de un expediente real |
| Cambios en módulos baseline | No implementado | El catálogo detecta módulos faltantes o no aprobados | Flujo separado de issue, pruebas y PR baseline |

## Evidencia que no debe confundirse

- Las pruebas de receipts GitHub demuestran validación local; no demuestran que
  se haya creado un PR remoto.
- La prueba PostgreSQL solo es evidencia PostgreSQL cuando se ejecuta con una URL
  aislada o en el servicio del job CI.
- El consumidor FinOps de pruebas verifica compatibilidad del contrato, pero no
  sustituye al agente 4 ni consulta precios AWS.
- El render del diagrama valida generación determinista; no valida por sí solo
  que la arquitectura sea adecuada para un cliente.
- La prueba unitaria del adaptador usa un proceso controlado. La prueba
  `test_real_pinned_awsdac_renders_generated_architecture` es la que demuestra la
  ejecución del binario real y permanece separada.
- No se ejecuta Terraform ni se despliega infraestructura AWS.

## Comandos locales reproducibles

Desde `project/backend`:

```powershell
.\.venv\Scripts\python.exe -m ruff format --check app tests
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q tests\architecture_agent
```

La prueba PostgreSQL requiere además una base desechable:

```powershell
$env:WORKFLOW_TEST_POSTGRES_URL = "postgresql://usuario:clave@localhost/architecture_test"
.\.venv\Scripts\python.exe -m pytest -q tests\architecture_agent\test_persistence_metrics.py
```

## Condición de cierre

El issue #19 no está cerrado. Antes de declararlo completo faltan la ejecución
remota GitHub MCP, la aprobación real del PR, la entrega al MCP real de FinOps,
la evidencia verde de CI/PostgreSQL y el flujo de modificación de baselines.
