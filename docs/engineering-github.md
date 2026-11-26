# Automatización GitHub y aviso de ingeniería — #21

El servicio publica un commit **ya probado y existente en el repositorio del
proyecto**, solicita revisión al arquitecto y permite integrar después de verificar
la aprobación exacta y CI. No ejecuta Terraform, emuladores, inferencia ni revisiones
en nombre del arquitecto. Las herramientas que publican o integran se invocan
únicamente por instrucción expresa del operador.

## Requisitos

- Recepción vigente, decisiones de Arquitectura/FinOps y archivos archivados.
- Corrida local completa y exitosa; para integrar, otra corrida CI exitosa del
  mismo commit/manifiesto, con referencia a GitHub Actions del proyecto.
- `main` con protección clásica: al menos una aprobación obligatoria,
  invalidación de aprobaciones antiguas, comprobaciones estrictas configuradas,
  aplicación a administradores y sin force push. Un repositorio que solo use
  rulesets requiere adaptar la verificación; no se interpreta como protegido.
- Baselines fijados al head o merge del PR aprobado e integrado. La API debe
  acreditar la aprobación del responsable indicado y el mismo árbol del módulo.
- Identidades de arquitecto y responsables de baselines compatibles con sus
  logins de GitHub. El operador local sigue siendo el responsable del expediente.

Se reutiliza `ProjectGitHub` para autenticación: `GITHUB_TOKEN`, `GH_TOKEN` o sesión
local de `gh`. Mantener las credenciales fuera de Git. El token requiere acceso
al proyecto y lectura de baselines: Contents y Pull requests para publicar,
Administration de lectura para protección, Actions/Checks/Commit statuses de
lectura para CI. El permiso para integrar sigue sujeto a la protección del repo.

## Operación

Desde `project/backend`, configurar `WORKFLOW_DATABASE_URL`, `ENGINEERING_OPERATOR`
y `ENGINEERING_ARTIFACTS_DIR`. Se leen los valores privados mediante el cargador
existente. `ENGINEERING_OPERATOR`, `DELIVERY_ENGAGEMENT_MANAGER` y
`WORKFLOW_MANAGER_ID` deben identificar al mismo responsable local registrado.
Si el proceso usa un checkpoint separado, conservar su `WORKFLOW_CHECKPOINT_URL`;
los comandos lo reutilizan. Sin esa configuración se usa el mismo PostgreSQL.

Preparar `publicacion.json` con `intake_id`, `local_run_id` y una rama
`engineering/<nombre>`. Ejecutar:

```powershell
python -m app.cli.engineering publish --input publicacion.json
```

Se comprueban baselines, protección y bytes remotos de implementación. Se crea
una referencia al commit probado, sin sobrescribir una rama distinta; se abre o
recupera el PR marcado por recepción/commit. El cuerpo referencia los insumos y
evidencias con hashes y se solicita revisión al arquitecto.

Después de la revisión, preparar `integracion.json` con `intake_id`, `ci_run_id`,
`revision` y `compatibility_limits` (lista de límites observados). Ejecutar:

```powershell
python -m app.cli.engineering integrate --input integracion.json
```

La integración vuelve a consultar baselines, ejecución Actions, comprobaciones
obligatorias y revisión del arquitecto sobre el head exacto. El PR no puede
contener archivos modificados sin respaldo en el manifiesto de implementación.
El merge utiliza `sha` y `merge_method=merge`; GitHub aplica sus reglas normales.
Se comprueban los archivos del commit resultante y se conserva el recibo externo.
Una respuesta perdida se recupera consultando el PR, sin repetir un merge exitoso.

Las transiciones exactas de etapa 5 se registran en el grafo a partir de esa
revisión verificada. Se conserva la entrega definitiva con su catálogo y se
encola el aviso en la misma transacción SQL. Un fallo entre GitHub, checkpoint
y registro final se recupera repitiendo la misma solicitud; no hay una transacción
distribuida entre esos sistemas.

El MCP privado de ingeniería ofrece las mismas operaciones mediante
`publicar_pr_ingenieria` e `integrar_pr_ingenieria`. Los contratos se consultan
desde `EngineeringPublication` y `EngineeringIntegration` en
`app.delivery.engineering_models`.

## Notificación

La entrega definitiva encola una tarea `slack` con ID estable
`engineering-notice:<intake_id>`. El worker existente la envía al
`SLACK_EM_USER_ID` configurado, guarda canal/fecha de Slack y no la duplica al
reimportar la entrega. El aviso no reemplaza el estado de preparación.

`consultar_ingenieria` muestra `publication`, `release` y `notification`. Los fallos
transitorios admiten reintento; un envío de resultado incierto queda en `uncertain`
y requiere conciliación externa antes de repetirlo. No se interpreta una ausencia
de respuesta como ausencia de mensaje. Los tokens de Slack permanecen privados.

Las pruebas consultan GitHub/Slack simulados y PostgreSQL aislado. La verificación
de Actions acredita su estado, commit y checks; no autentica retrospectivamente
el contenido de logs importados ni acredita compatibilidad completa con AWS real.
El piloto real requiere las entregas aprobadas de #19/#20 y permisos configurados.

Referencias de los contratos externos: [revisiones GitHub](https://docs.github.com/en/rest/pulls/reviews),
[protección de ramas](https://docs.github.com/en/rest/branches/branch-protection),
[ejecuciones Actions](https://docs.github.com/en/rest/actions/workflow-runs) y
[integración de PRs](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request).
