# 2. Meeting Assistant

Agent 2 abre el proyecto después de que dirección haya tomado una decisión. La
reunión, la presentación y la decisión ocurren fuera del agente. Stuart gestiona
la decisión desde un chat de IA conectado por MCP; el agente guía la conversación
y solo crea recursos en GitHub después de una confirmación final.

El runtime vive en `project/backend/app/project_opening/`. El grafo de apertura
usa LangGraph y un checkpointer PostgreSQL. Esta carpeta conserva la entrada,
las instrucciones y la plantilla del issue; no se importa como paquete Python.

## Conversación en el chat

El MCP lleva a Stuart por estas preguntas, en orden:

1. ¿Qué proyecto preparado quiere gestionar? (número de la lista, nombre o `case_id`)
2. ¿Dirección aprobó o rechazó que continúe?
3. Si fue rechazado, ¿confirma el rechazo?
4. Si fue aprobado, ¿en qué posición debe quedar en la cola actual?
5. ¿Cuál es el presupuesto total aprobado en USD?
6. ¿Qué usuario de GitHub será el arquitecto asignado? El MCP verifica en GitHub,
   solo con lectura, que el usuario exista.
7. ¿Confirma el resumen y la creación del repositorio, la publicación de los archivos
   aprobados y el issue asignado?

El resumen final muestra el título y el nombre previstos del repositorio, el template,
los nombres de los archivos que se publicarán y el issue de arquitectura con su
asignado. Si una respuesta no es válida, la misma pregunta vuelve con un campo
`error` que explica el motivo.

Un rechazo confirmado se guarda en PostgreSQL, acepta la entrega del agente 1 y
termina sin escrituras en GitHub. El proyecto sale de la lista de preparados y no se
puede aprobar después desde otra sesión; el Engagement Manager se encarga. Una
cancelación, en la confirmación del rechazo o en la final, no registra la decisión
ni crea recursos. La sesión conversacional
y las respuestas pendientes se guardan en checkpoints LangGraph para poder
continuar después de reiniciar el proceso.

## Conexión local y ChatGPT

Configurar `WORKFLOW_DATABASE_URL` con una base PostgreSQL de workflow y
`AGENT2_MCP_BEARER_TOKEN` con un token privado de al menos 32 caracteres en
`secrets.env`. El token no se guarda en Git.

Genera un token local con `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`, guárdalo en el `secrets.env` privado y configura el mismo valor como Bearer en la conexión de ChatGPT. No lo pongas en `project/.env` ni en la configuración versionada del túnel.

```sh
make agent2-http
```

Esto sirve Streamable HTTP en `http://127.0.0.1:8768/mcp`, protegido con Bearer.
Desde ChatGPT, conectar el servidor local a través del Secure MCP Tunnel ya
configurado, apuntando a `/mcp` y usando el token. Para probar con un cliente
MCP local por STDIO:

```sh
make agent2
```

ChatGPT conecta con servidores MCP remotos; el túnel seguro permite usar este
servidor local sin abrirlo a Internet. La disponibilidad de conexiones MCP con
acciones de escritura depende del plan y permisos del espacio de trabajo de
ChatGPT.

## Persistencia y entrega

La decisión, el orden de cola, el presupuesto, el arquitecto, el expediente,
los eventos y los checkpoints se guardan en la base PostgreSQL de workflow. La
exportación aprobada del agente 1 conserva en PostgreSQL los bytes de los cinco archivos corporativos (o del contrato anterior aprobado) y su manifiesto, además de sus hashes. La apertura verifica la entrega
y publica los mismos bytes en `docs/01-discovery/`.

Cuando Stuart confirma, LangGraph crea el repositorio desde
`marcor0311/aws-cloud-consulting-project-template`, publica el paquete en
`docs/initial-structure`, abre y verifica el merge del PR, y crea el issue de
arquitectura según `templates/architecture.md`. El issue se asigna al arquitecto
indicado. Los reintentos concilian estado remoto antes de repetir efectos; no
fuerzan ramas ni reemplazan cambios humanos.

### Lead Time y Process Time

La fase `stage-2` mide el tiempo en Dirección: empieza cuando el agente 1 entrega
el paquete aprobado y termina cuando se registra la aprobación o el rechazo. La fase
`project-opening` mide la apertura en GitHub hasta el handoff al arquitecto; su
Process Time son las sesiones de trabajo registradas del agente. La herramienta MCP
`consultar_metricas_apertura` devuelve ambas fases y los handoffs con su espera.
No se infieren tiempos que no estén registrados.

Los nombres siguen esta convención:

```text
AWS Cloud Consulting Project <Compañía> <NN> <Proyecto>
aws-cloud-consulting-project-<compañía>-<nn>-<proyecto>
```

El número por compañía y la posición en la cola se reservan en PostgreSQL.
Nuevos proyectos usan `aws-cloud-consulting-group`; el template se mantiene en
la cuenta personal autorizada.

## Operación local

```sh
make agent2-http       # Streamable HTTP local para el Secure MCP Tunnel
make agent2            # Transporte STDIO local
make agent2-preview    # Preview aislado, sin llamadas a GitHub
make agent2-queue      # Consultar la cola persistida
```

Las operaciones de GitHub usan credenciales separadas del token MCP. El agente
no consume inferencia para registrar una decisión ni para abrir el repositorio.
Los documentos se entregan como datos; no pueden alterar las instrucciones ni
otorgar aprobación.

## Verificación

```sh
cd project/backend
.venv/bin/python -m pytest -q tests/project_opening
```

La suite normal usa mocks offline. El recorrido PostgreSQL se ejecuta solo con
`WORKFLOW_TEST_POSTGRES_URL` aislada; el E2E de voz usa LiveKit, correo,
Calendar, transcripciones y proveedores simulados, sin llamadas externas.
