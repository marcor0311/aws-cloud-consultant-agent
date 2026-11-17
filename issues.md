# Issues de agentes

Seis agentes del proceso orquestados por medio de **LangGraph y PostgreSQL**.

> **Nota para todos los agentes:** Registrar **Lead Time** y **Process Time** según [AWS](https://docs.aws.amazon.com/prescriptive-guidance/latest/strategy-devops-value-stream-mapping/introduction.html). Guardar las mediciones y los handoffs en PostgreSQL para la orquestación.

## 1. Engagement Manager — Agendamiento y preparación ejecutiva

```mermaid
%%{init: {"theme": "base", "look": "classic", "fontFamily": "Arial, sans-serif", "themeVariables": {"darkMode": false, "background": "#ffffff", "fontFamily": "Arial, sans-serif", "fontSize": "16px", "primaryColor": "#eff6ff", "primaryTextColor": "#0f172a", "primaryBorderColor": "#2563eb", "lineColor": "#64748b", "edgeLabelBackground": "#ffffff", "clusterBkg": "#ffffff", "clusterBorder": "#ffffff"}, "flowchart": {"diagramPadding": 0, "wrappingWidth": 320, "nodeSpacing": 32, "rankSpacing": 32, "padding": 16}}}%%
flowchart TB
    subgraph lienzo[" "]
        direction TB
        cliente["El cliente solicita<br/>una reunión"] --> voz["Agente de agendamiento"]
        voz --> registro{"¿Cliente registrado?"}
        registro -->|No| asesor["Contactar a un asesor<br/>de negocio"]
        registro -->|Sí| codigo["Enviar y verificar<br/>el código por correo"]
        codigo -->|Código válido| agenda["Confirmar la reunión inicial"]
        agenda --> reunion["Reunión del cliente<br/>con el Engagement Manager"]
        reunion --> preparacion["Agente de preparación<br/>Trabaja con el Engagement Manager"]
        preparacion --> entrega["Resumen ejecutivo, presentación<br/>y transcripción PDF revisados y aprobados<br/>por el Engagement Manager"]
        classDef default fill:#eff6ff,stroke:#2563eb,color:#0f172a;
        classDef inicio fill:#fff7ed,stroke:#d97706,color:#7c2d12;
        classDef handoff fill:#ecfdf5,stroke:#059669,color:#064e3b;
        class cliente inicio;
        class entrega handoff;
    end
    style lienzo fill:#ffffff,stroke:#ffffff,stroke-width:128px;
```

**Stack recomendado:**

- **Agendamiento:** SwiftUI y LiveKit.
- **Preparación:** ChatGPT, Claude o una interfaz web con cliente MCP; GitHub para los repositorios de proyectos.
- **Orquestación y datos:** LangGraph y PostgreSQL.

**Herramientas recomendadas:** Google Calendar, Gmail API, endpoint de whitelist y MCP del procesador documental.

**Entrada:**

- **Agendamiento:** solicitud del cliente, correo y disponibilidad para la reunión inicial.
- **Preparación:** transcripción y notas de la reunión, sin comparar otros proyectos.

**Entrega:** reunión inicial confirmada; resumen ejecutivo, presentación y transcripción PDF limpia aprobados por el Engagement Manager para presentar a dirección ejecutiva.

**Funcionalidades:**

- [ ] **Agendamiento:** verificar el registro y el código por correo, consultar disponibilidad y confirmar la reunión; gestionar cancelaciones y reprogramaciones, y remitir al asesor a quienes no estén registrados.
- [ ] **Preparación ejecutiva:** procesar la transcripción completa de Stuart y generar exactamente tres entregables: resumen ejecutivo, presentación y transcripción PDF limpia. El resumen y la presentación incluyen objetivo, problema, alcance, necesidades, requisitos, integraciones, restricciones, presupuesto, plazos, riesgos y decisiones de la reunión. No añadir descubrimiento, preguntas nuevas, comparaciones ni guion.

## 2. Aprobación y apertura del proyecto

```mermaid
%%{init: {"theme":"base","themeVariables":{"darkMode":false,"background":"#ffffff","primaryColor":"#eff6ff","primaryTextColor":"#0f172a","primaryBorderColor":"#2563eb","lineColor":"#64748b","edgeLabelBackground":"#ffffff","clusterBkg":"#ffffff","clusterBorder":"#cbd5e1"},"flowchart":{"diagramPadding":0}}}%%
flowchart TB
    subgraph lienzo[" "]
        direction TB
        insumos["Paquete aprobado por el Engagement Manager"] --> identificar["El MCP pregunta<br/>qué proyecto gestionar"]
        identificar --> aprobacion{"¿Dirección aprobó<br/>el proyecto?"}
        aprobacion -->|No| fin["Registrar el rechazo<br/>y cerrar el flujo"]
        aprobacion -->|Sí| prioridad["Preguntar la prioridad<br/>en la cola actual"]
        prioridad --> presupuesto["Preguntar el presupuesto<br/>aprobado"]
        presupuesto --> arquitecto["Preguntar el arquitecto asignado"]
        arquitecto --> confirmar["Resumir los datos y las acciones;<br/>pedir confirmación a Stuart"]
        confirmar --> repo["Crear el repo desde el template<br/>y cargar los insumos aprobados"]
        repo --> entrega["Crear y asignar el issue<br/>de arquitectura"]
        classDef default fill:#eff6ff,stroke:#2563eb,color:#0f172a;
        classDef inicio fill:#fff7ed,stroke:#d97706,color:#7c2d12;
        classDef handoff fill:#ecfdf5,stroke:#059669,color:#064e3b;
        class insumos inicio;
        class entrega handoff;
    end
    style lienzo fill:#ffffff,stroke:#ffffff,stroke-width:128px;
```

**Objetivo:** permitir que Stuart registre y gestione la decisión de dirección desde un chat de IA conectado al MCP del proyecto. El chat puede ser ChatGPT, Claude u otro cliente compatible con MCP.

**Entrada:** paquete del proyecto preparado y aprobado por el Engagement Manager, con los tres PDF: resumen ejecutivo, presentación y transcripción limpia. La reunión y la decisión de dirección ocurren fuera del sistema; el agente no presenta, responde preguntas ni organiza votaciones.

**Flujo conversacional:** Stuart inicia la gestión desde un chat de IA conectado al MCP. El MCP le pregunta cuál proyecto quiere gestionar y, para ese proyecto, si dirección aprobó o rechazó su continuación. Si fue rechazado, registra la decisión y termina el flujo. Si fue aprobado, pregunta en orden la prioridad del proyecto en la cola actual, el presupuesto autorizado y el arquitecto asignado. Luego presenta un resumen de la decisión y los datos, explica que creará el repositorio desde el template, cargará los insumos aprobados y abrirá el issue de arquitectura asignado; solo continúa cuando Stuart confirma.

**Resultado:** un rechazo queda registrado sin crear recursos en GitHub. Tras la confirmación de Stuart para un proyecto aprobado, el MCP registra la decisión y los datos acordados, crea el repositorio a partir de `aws-cloud-consulting-project-template`, carga los insumos aprobados y crea el issue de arquitectura asignado al arquitecto indicado.

**Criterios de aceptación:**

- [ ] Al iniciar, el MCP pregunta cuál proyecto preparado quiere gestionar Stuart.
- [ ] Para el proyecto elegido, el MCP pregunta si dirección aprobó o rechazó su continuación.
- [ ] Si fue rechazado, registra la decisión y no crea repositorio ni issue.
- [ ] Si fue aprobado, pregunta la prioridad en la cola actual, el presupuesto aprobado y el arquitecto asignado.
- [ ] Antes de crear recursos, presenta a Stuart un resumen de los datos y las acciones previstas, y espera su confirmación.
- [ ] Tras la confirmación, valida y persiste la decisión y los datos; crea el repositorio desde `aws-cloud-consulting-project-template`, carga los insumos aprobados y crea el issue de arquitectura asignado al arquitecto.

## 3. Cloud Solutions Architect — Diseño

```mermaid
%%{init: {"theme":"base","themeVariables":{"darkMode":false,"background":"#ffffff","primaryColor":"#eff6ff","primaryTextColor":"#0f172a","primaryBorderColor":"#2563eb","lineColor":"#64748b","edgeLabelBackground":"#ffffff","clusterBkg":"#ffffff","clusterBorder":"#cbd5e1"},"flowchart":{"diagramPadding":0}}}%%
flowchart TB
    subgraph lienzo[" "]
        direction TB
        arquitecto["Issue asignado al arquitecto<br/>Notificación de GitHub"]
        subgraph proyecto["Repo del proyecto creado desde template"]
            agenteProyecto["Agente del proyecto<br/>Codex"]
            diseno["Especificación, plan y diagrama AWS como código<br/>ADRs con tradeoffs, políticas como código y costos"]
            agenteProyecto --> diseno
        end
        subgraph baselines["Repo de baseline modules"]
            agenteBaselines["Agente de baselines<br/>Codex"]
            cambios["Crear, modificar o eliminar módulos<br/>Pruebas y PR"]
            aprobacionBaseline["Arquitecto aprueba el PR"]
            catalogo["Catálogo y módulos versionados"]
            agenteBaselines --> cambios --> aprobacionBaseline --> catalogo
        end
        arquitecto -.-> agenteProyecto
        arquitecto -.-> agenteBaselines
        agenteProyecto <-->|GitHub MCP| catalogo
        diseno --> pr["El agente abre el PR de arquitectura"]
        pr --> aprobacion["Arquitecto revisa y aprueba"]
        aprobacion --> entrega["Issue asignado a FinOps<br/>Notificación nativa de GitHub"]
        classDef default fill:#eff6ff,stroke:#2563eb,color:#0f172a;
        classDef inicio fill:#fff7ed,stroke:#d97706,color:#7c2d12;
        classDef handoff fill:#ecfdf5,stroke:#059669,color:#064e3b;
        class arquitecto inicio;
        class entrega handoff;
    end
    style lienzo fill:#ffffff,stroke:#ffffff,stroke-width:128px;
```

**Stack recomendado:** Codex, LangGraph y PostgreSQL.

**Herramientas recomendadas:**

- [Agent Toolkit for AWS](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/what-is-agent-toolkit.html)
- [AWS DevOps Agent](https://docs.aws.amazon.com/devopsagent/latest/userguide/working-with-devops-agent-accessing-devops-agent-index.html)
- [AWS Security Agent](https://docs.aws.amazon.com/securityagent/latest/userguide/what-is.html)

> Acceso complementario: sesiones de Codex separadas para proyecto y baselines; [GitHub MCP](https://github.com/github/github-mcp-server) para acceso directo a módulos e issues/PRs; MCP del backend para tiempos, handoffs y coordinación con LangGraph. AWS Pricing MCP, AWS MCP y Terraform MCP configurados para el puesto.

**Entrada:** issue de arquitectura en el repo del proyecto creado desde `aws-cloud-consulting-project-template`, con los insumos previos. Llega desde la aprobación del proyecto en el diagrama 2 o desde una corrección solicitada por el agente FinOps en el diagrama 4, con el problema y el enlace a la revisión que requirió ajustes.

**Entrega:** el agente de Codex cierra el issue de arquitectura y crea un nuevo issue asignado a FinOps en el mismo repo, con diseño aprobado, commit, versiones de módulos y enlaces a los issues anteriores. GitHub notifica la asignación.

**Funcionalidades:**

- [ ] Trabajar con el agente del repo del proyecto para documentar requisitos, plan, **diagrama de arquitectura AWS como código**, ADRs con tradeoffs, **políticas como código** y estimación inicial.
- [ ] Consultar directamente el catálogo, código, documentación y versiones de baselines mediante GitHub MCP para seleccionar los módulos de la arquitectura.
- [ ] Crear, modificar o eliminar módulos en `aws-cloud-consultant-baseline-modules` con su propio agente, pruebas, revisión del impacto en consumidores y PR.
- [ ] Los PRs de arquitectura y baselines requieren la aprobación del arquitecto.
- [ ] El agente de Codex abre el PR de arquitectura al terminar el diseño y solicita la revisión del arquitecto, apoyándose en las herramientas AWS habilitadas.
- [ ] Atender los issues de corrección abiertos por el agente FinOps. Actualizar los módulos y los documentos afectados, mantener coherentes el diagrama, las versiones, los supuestos y los costos, y solicitar la aprobación del arquitecto.
- [ ] Tras la aprobación del arquitecto, el agente de Codex cierra el issue atendido y crea un nuevo issue para FinOps mediante GitHub MCP, con commit, diagrama, recursos, región, supuestos, presupuesto, versiones de baselines y referencias a los issues anteriores. GitHub gestiona el aviso y LangGraph registra el handoff.

## 4. FinOps Analyst — Costos

```mermaid
%%{init: {"theme":"base","themeVariables":{"darkMode":false,"background":"#ffffff","primaryColor":"#eff6ff","primaryTextColor":"#0f172a","primaryBorderColor":"#2563eb","lineColor":"#64748b","edgeLabelBackground":"#ffffff","clusterBkg":"#ffffff","clusterBorder":"#cbd5e1"},"flowchart":{"diagramPadding":0}}}%%
flowchart TB
    subgraph lienzo[" "]
        direction TB
        issue["Issue asignado a la persona de FinOps<br/>Notificación nativa de GitHub"] --> externo["FinOps trabaja con el agente<br/>Consulta las tareas y los insumos"]
        externo --> calculadora["Tool: generar_estimacion_aws<br/>Enlace de AWS Pricing Calculator"]
        externo --> excel["Tool: generar_excel_costos<br/>Excel de proyecciones y escenarios"]
        calculadora --> validar{"¿Insumos coherentes<br/>y dentro del presupuesto?"}
        excel --> validar
        validar -->|No| ajustes["El agente cierra el issue de FinOps<br/>con label requiere-ajustes"]
        ajustes --> devolucion["Abre un nuevo issue para el arquitecto<br/>con el problema y el enlace al anterior<br/>Continúa al inicio del diagrama 3"]
        validar -->|Sí| confirmar["FinOps confirma la entrega<br/>desde el chat por MCP"]
        confirmar --> publicar["Publicar ambos insumos en docs/04-finops/<br/>de la rama de trabajo"]
        publicar --> pr["El agente abre e integra el PR de costos"]
        pr --> cierre["El agente cierra el issue de FinOps"]
        cierre --> entrega["Abre un nuevo issue para el<br/>Cloud Infrastructure Engineer<br/>con arquitectura y costos validados"]
        classDef default fill:#eff6ff,stroke:#2563eb,color:#0f172a;
        classDef inicio fill:#fff7ed,stroke:#d97706,color:#7c2d12;
        classDef handoff fill:#ecfdf5,stroke:#059669,color:#064e3b;
        class issue inicio;
        class entrega,devolucion handoff;
    end
    style lienzo fill:#ffffff,stroke:#ffffff,stroke-width:128px;
```

**Stack recomendado:** tools por MCP desde ChatGPT, Claude o una interfaz web con cliente MCP; LangGraph y PostgreSQL.

FinOps aprueba los documentos desde el chat y el agente abre e integra el PR de costos. Este flujo requiere que las reglas de la rama permitan esa integración tras las comprobaciones, sin revisión del arquitecto. GitHub no permite aprobar un PR propio. [Documentación de GitHub](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/approving-a-pull-request-with-required-reviews).

**Herramientas recomendadas:**

[Agent Toolkit for AWS](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/what-is-agent-toolkit.html), [AWS DevOps Agent](https://docs.aws.amazon.com/devopsagent/latest/userguide/working-with-devops-agent-accessing-devops-agent-index.html) y [AWS Security Agent](https://docs.aws.amazon.com/securityagent/latest/userguide/what-is.html).

> Acceso complementario: **GitHub MCP** para consultar tareas, comentar y publicar resultados; MCP del backend para acciones del flujo con LangGraph. AWS Pricing MCP, AWS MCP y Terraform MCP configurados para el puesto.

Tools propias por implementar y exponer por MCP:

| Tool | Resultado |
| --- | --- |
| `generar_estimacion_aws` | Automatizar la calculadora web y obtener el [enlace real de la estimación guardada](https://docs.aws.amazon.com/pricing-calculator/latest/userguide/save-share-estimate.html), con respaldo CSV/PDF. |
| `generar_excel_costos` | Crear `forecast.xlsx` con costos por recurso, fórmulas, proyecciones mensuales/anuales y escenarios. |

**Entrada:** nuevo issue asignado a FinOps con diseño aprobado o corregido, commit, módulos, recursos, región, supuestos y presupuesto. Si viene de una corrección, incluye los enlaces a la revisión anterior y al issue de arquitectura. Requiere cuenta GitHub con acceso al repo; el trabajo se realiza desde el chat.

**Entrega:**

- **Si cumple:** tras la aprobación de FinOps desde el chat, el agente abre e integra el PR de costos, cierra el issue de FinOps y crea uno nuevo en el mismo repo, asignado al **Cloud Infrastructure Engineer**, para iniciar el desarrollo. Incluye commit, PR de costos, arquitectura, enlace de AWS Pricing Calculator, Excel en `docs/04-finops/` y referencia al issue cerrado. GitHub notifica la asignación.
- **Si requiere ajustes:** el agente cierra el issue FinOps con el label `requiere-ajustes` y abre otro en el mismo repo, asignado al arquitecto, con el problema y las referencias a los insumos revisados. El flujo continúa al inicio del diagrama 3.

**Funcionalidades:**

- [ ] Consultar las tareas asignadas y trabajarlas desde ChatGPT, Claude o web mediante GitHub MCP.
- [ ] Ayudar al FinOps Analyst a redactar y publicar comentarios en el issue con dudas de arquitectura, diferencias de costos o ajustes solicitados. Mencionar al arquitecto asignado con su usuario real de GitHub (`@usuario-del-arquitecto`) e incluir referencias al diseño o a la estimación correspondiente.
- [ ] Cuando el diseño requiera cambios, el agente FinOps cierra la revisión con el label `requiere-ajustes` y crea un issue de corrección asignado al arquitecto, con el problema, los insumos afectados y el enlace al issue cerrado.
- [ ] Recibir el nuevo issue creado por Codex tras la corrección y validar el commit actualizado, regenerando la estimación y el Excel según los cambios. Mantener los enlaces entre las revisiones y las correcciones.
- [ ] Generar ambos insumos y validar supuestos, totales y presupuesto; solicitar ajustes cuando corresponda.
- [ ] Tras la aprobación de FinOps desde el chat, el agente publica los insumos y abre el PR de costos con el enlace de la estimación y el Excel. Integra el PR conforme a las reglas de la rama, cierra el issue de costos y crea uno nuevo para el Cloud Infrastructure Engineer con los entregables y el enlace al issue anterior. El backend conecta los webhooks de GitHub con LangGraph, registra estado y tiempos en PostgreSQL y evita handoffs duplicados. Los cierres con `requiere-ajustes` se registran como devoluciones y retrabajo; la fase termina al integrar los documentos aprobados por FinOps y confirmar la entrega a ingeniería.

## 5. Cloud Infrastructure Engineer — Implementación

```mermaid
%%{init: {"theme":"base","themeVariables":{"darkMode":false,"background":"#ffffff","primaryColor":"#eff6ff","primaryTextColor":"#0f172a","primaryBorderColor":"#2563eb","lineColor":"#64748b","edgeLabelBackground":"#ffffff","clusterBkg":"#ffffff","clusterBorder":"#cbd5e1"},"flowchart":{"diagramPadding":0}}}%%
flowchart TB
    subgraph lienzo[" "]
        direction TB
        issue["Nuevo issue asignado por FinOps<br/>Arquitectura, módulos y dos insumos de costos"] --> agente["Ingeniero trabaja con Codex<br/>Mismo repo del arquitecto"]
        agente -->|Consulta mediante GitHub MCP| baselines["Repo de baseline modules"]
        baselines -->|Módulos con versión aprobada| implementar
        agente --> implementar["Implementar Terraform<br/>con módulos versionados"]
        implementar --> validar["Pruebas, seguridad y políticas como código"]
        validar --> local["Despliegue local<br/>Documentación y evidencias"]
        local --> pr["El agente abre el PR de implementación"]
        pr --> arquitecto["Arquitecto revisa y aprueba"]
        arquitecto --> main["Integrar en main protegido"]
        main --> entrega["Notificar al Engagement Manager"]
        classDef default fill:#eff6ff,stroke:#2563eb,color:#0f172a;
        classDef inicio fill:#fff7ed,stroke:#d97706,color:#7c2d12;
        classDef handoff fill:#ecfdf5,stroke:#059669,color:#064e3b;
        class issue inicio;
        class entrega handoff;
    end
    style lienzo fill:#ffffff,stroke:#ffffff,stroke-width:128px;
```

**Stack recomendado:** Codex, Terraform, AWS Emulator, GitHub Actions, LangGraph y PostgreSQL.

**Herramientas recomendadas:**

- [AWS Emulator](https://github.com/aws/aws-emulator) y su [skill oficial `aws-emulator`](https://docs.aws.amazon.com/emulator/latest/userguide/getting-started-agent.html): entorno oficial de pruebas locales de Terraform.
- [Agent Toolkit for AWS](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/what-is-agent-toolkit.html)
- [AWS DevOps Agent](https://docs.aws.amazon.com/devopsagent/latest/userguide/working-with-devops-agent-accessing-devops-agent-index.html)
- [AWS Security Agent](https://docs.aws.amazon.com/securityagent/latest/userguide/what-is.html)

> Acceso complementario: el mismo **GitHub MCP** para trabajar en el repo del proyecto y leer `aws-cloud-consultant-baseline-modules`. AWS Pricing MCP, AWS MCP y Terraform MCP configurados para el puesto.

**Entrada:** nuevo issue creado por el agente FinOps en el mismo repo del proyecto donde trabajó el arquitecto, con rama/commit, requisitos, diseño, módulos, enlace de AWS Pricing Calculator y Excel de costos validados; entorno y accesos preparados.

**Entrega:** PR abierto por el agente de Codex en el mismo repo con los cambios de ingeniería, documentación, pruebas y evidencias locales, para revisión y aprobación del arquitecto. Los documentos de FinOps ya están integrados y se referencian desde la implementación.

**Funcionalidades:**

- [ ] Implementar la infraestructura con Codex en el repo del proyecto, a partir del diseño aprobado.
- [ ] Consultar baselines por GitHub MCP y reutilizar módulos aprobados y versionados. Antes de implementar, Codex revisa con `aws-emulator` la compatibilidad de servicios AWS y módulos Terraform, y la confirma con pruebas reales en el emulador.
- [ ] Automatizar `terraform fmt`, `validate`, `plan`, `apply` y `destroy`, pruebas de integración, análisis de seguridad y políticas como código. Ejecutar las pruebas de integración con AWS Emulator localmente y en GitHub Actions, sin credenciales reales ni costos de infraestructura AWS; asegurar la limpieza incluso ante fallos.
- [ ] Mantener un catálogo versionado de servicios y recursos Terraform probados, con versiones, éxitos, errores y limitaciones. Guardar evidencias, resultados, Lead Time y Process Time mediante LangGraph/PostgreSQL.
- [ ] El agente de Codex abre el PR de implementación al terminar las pruebas, con documentación, evidencias y referencias a los insumos de FinOps, y solicita la revisión y aprobación obligatoria del Cloud Solutions Architect.
- [ ] Notificar al Engagement Manager cuando el PR esté aprobado.

> Distinguir errores de Terraform de limitaciones del emulador. Las pruebas exitosas no garantizan compatibilidad completa con AWS real ni validan sus controles de seguridad; los análisis de seguridad y políticas se ejecutan por separado.

## 6. Engagement Manager — Informe ejecutivo

```mermaid
%%{init: {"theme":"base","themeVariables":{"darkMode":false,"background":"#ffffff","primaryColor":"#eff6ff","primaryTextColor":"#0f172a","primaryBorderColor":"#2563eb","lineColor":"#64748b","edgeLabelBackground":"#ffffff","clusterBkg":"#ffffff","clusterBorder":"#cbd5e1"},"flowchart":{"diagramPadding":0}}}%%
flowchart TB
    subgraph lienzo[" "]
        direction TB
        interfaz["Engagement Manager<br/>ChatGPT, Claude o interfaz web"] --> mcp["MCP del backend"]
        mcp --> agente
        insumos["Entrega técnica, costos,<br/>decisiones y evidencias"] --> agente["Agente consolida resultados<br/>Lead Time y Process Time según AWS"]
        tiempos[("PostgreSQL<br/>Tiempos y handoffs de todas las fases")] --> agente
        agente --> informe["Informe ejecutivo en PDF<br/>Resultados, presupuesto y siguientes pasos"]
        informe --> revision["Engagement Manager revisa<br/>desde la misma interfaz"]
        revision -->|Solicitar ajustes| agente
        revision -->|Aprobar y descargar PDF| presentacion["Presentar a dirección"]
        presentacion --> entrega["Informe aprobado y proyecto cerrado"]
        classDef default fill:#eff6ff,stroke:#2563eb,color:#0f172a;
        classDef inicio fill:#fff7ed,stroke:#d97706,color:#7c2d12;
        classDef handoff fill:#ecfdf5,stroke:#059669,color:#064e3b;
        class interfaz inicio;
        class entrega handoff;
    end
    style lienzo fill:#ffffff,stroke:#ffffff,stroke-width:128px;
```

**Stack recomendado:** ChatGPT, Claude o interfaz web con cliente MCP; LangGraph y PostgreSQL.

**Herramientas recomendadas:** MCP propio con tools para consultar métricas, generar PDF y registrar aprobación; GitHub MCP para consultar entregables; Gmail API o Slack para notificaciones.

**Entrada:** entrega técnica, costos, decisiones, evidencias y tiempos de todas las fases.

**Entrega:** informe ejecutivo aprobado para dirección, descargable en PDF desde la interfaz, con documentos de respaldo.

**Funcionalidades:**

- [ ] Solicitar y revisar el informe desde ChatGPT, Claude o una interfaz web por MCP, sin usar GitHub.
- [ ] Consolidar Lead Time, Process Time, esperas y retrabajo, separando actividad humana y de agentes.
- [ ] Usar una librería de Python, como ReportLab, para generar informes PDF con formato corporativo estándar para Executive Leadership, con resultados, presupuesto, pruebas locales y siguientes pasos para la aplicación.
- [ ] Permitir ajustes y aprobación del Engagement Manager desde la misma interfaz; presentar a dirección y cerrar el proyecto.
