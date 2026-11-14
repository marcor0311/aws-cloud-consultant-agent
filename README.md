# Consultoría de arquitectura AWS

AWS Cloud Consultant Agent es un sistema multiagente en desarrollo para apoyar
los puestos de una consultora en proyectos de nube. Los agentes utilizan
herramientas, ejecutan tareas y coordinan entregas entre negocio, arquitectura,
FinOps e ingeniería, desde la solicitud del cliente hasta el informe y cierre
de la fase de consultoría. Las personas revisan y aprueban los resultados.

El equipo consume las herramientas del sistema mediante MCP desde
ChatGPT/Claude y Codex/Claude Code. La agenda y el correo se integran mediante
las API de Google Calendar y Gmail.

> **Segunda iteración del proyecto**
>
> El repositorio original,
> [Proyecto-Multiagentes-Tendencias-en-Ingenieria-del-Software](https://github.com/marcor0311/Proyecto-Multiagentes-Tendencias-en-Ingenieria-del-Software),
> se desarrolló para el curso
> **PSWE-01 Tendencias en Ingeniería del Software**.
>
> Esta segunda iteración corresponde al curso
> **PSWE-07 Procesos y Administración de Software**.

## Tecnologías

**Aplicación**

<p>
  <img src="https://skillicons.dev/icons?i=py,fastapi,js,html,css" alt="Python, FastAPI, JavaScript, HTML y CSS" height="56">
  <img src="docs/assets/technology-icons/pydantic.svg" alt="Pydantic" title="Pydantic" width="56" height="56">
</p>

**Datos**

<p>
  <img src="https://skillicons.dev/icons?i=postgres,sqlite" alt="PostgreSQL y SQLite" height="56">
</p>

**Agentes e IA**

<p>
  <img src="docs/assets/technology-icons/langgraph.svg" alt="LangGraph" title="LangGraph" width="56" height="56">
  <img src="docs/assets/technology-icons/mcp.svg" alt="MCP" title="MCP" width="56" height="56">
  <img src="docs/assets/technology-icons/openai-chatgpt.svg" alt="OpenAI / ChatGPT" title="OpenAI / ChatGPT" width="56" height="56">
  <img src="docs/assets/technology-icons/claude.svg" alt="Claude" title="Claude" width="56" height="56">
  <img src="docs/assets/technology-icons/claude-code.svg" alt="Claude Code" title="Claude Code" width="56" height="56">
  <img src="docs/assets/technology-icons/github-copilot.svg" alt="GitHub Copilot" title="GitHub Copilot" width="56" height="56">
  <img src="docs/assets/technology-icons/codex.svg" alt="Codex" title="Codex" width="56" height="56">
  <img src="docs/assets/technology-icons/gemma.svg" alt="Gemma" title="Gemma" width="56" height="56">
</p>

**Voz y transcripción**

<p>
  <img src="docs/assets/technology-icons/livekit.svg" alt="LiveKit" title="LiveKit" width="56" height="56">
  <img src="docs/assets/technology-icons/assemblyai.svg" alt="AssemblyAI" title="AssemblyAI" width="56" height="56">
  <img src="docs/assets/technology-icons/gradium.svg" alt="Gradium" title="Gradium" width="56" height="56">
  <img src="docs/assets/technology-icons/ai-coustics.svg" alt="ai-coustics" title="ai-coustics" width="56" height="56">
  <img src="docs/assets/technology-icons/transcriptonic.svg" alt="TranscripTonic" title="TranscripTonic" width="56" height="56">
</p>

**Integraciones**

<p>
  <img src="docs/assets/technology-icons/gmail.svg" alt="Gmail" title="Gmail" width="56" height="56">
  <img src="docs/assets/technology-icons/google-calendar.svg" alt="Google Calendar" title="Google Calendar" width="56" height="56">
  <img src="docs/assets/technology-icons/google-meet.svg" alt="Google Meet" title="Google Meet" width="56" height="56">
  <img src="docs/assets/technology-icons/slack.svg" alt="Slack" title="Slack" width="56" height="56">
</p>

**Documentos y navegador**

<p>
  <img src="docs/assets/technology-icons/reportlab.svg" alt="ReportLab" title="ReportLab" width="56" height="56">
  <img src="docs/assets/technology-icons/playwright.svg" alt="Playwright" title="Playwright" width="56" height="56">
</p>

**Nube e infraestructura**

<p>
  <img src="https://skillicons.dev/icons?i=aws,terraform" alt="AWS y Terraform" height="56">
</p>

Para la etapa de ingeniería se recomienda [AWS Emulator](https://github.com/aws/aws-emulator)
con la [skill oficial `aws-emulator`](https://docs.aws.amazon.com/emulator/latest/userguide/getting-started-agent.html)
como entorno oficial de pruebas locales de Terraform y en GitHub Actions.
Su integración está definida en el [contrato de implementación](issues.md#5-cloud-infrastructure-engineer--implementación)
y está pendiente de desarrollo. Los resultados del emulador no garantizan
compatibilidad completa ni validan los controles de seguridad de AWS real.

**Control de versiones y CI**

<p>
  <img src="https://skillicons.dev/icons?i=git,github,githubactions" alt="Git, GitHub y GitHub Actions" height="56">
</p>

## Repositorios relacionados

Los repositorios de cada proyecto se crean y se trabajan dentro de la organización
[aws-cloud-consulting-group](https://github.com/aws-cloud-consulting-group).

El proyecto utiliza estos repositorios como insumos para el diseño y la
organización de los proyectos de consultoría:

| Repositorio | Propósito |
| --- | --- |
| [aws-cloud-consultant-baseline-modules](https://github.com/marcor0311/aws-cloud-consultant-baseline-modules) | Catálogo de módulos Terraform versionados para diseñar e implementar las arquitecturas AWS. |
| [aws-cloud-consulting-project-template](https://github.com/marcor0311/aws-cloud-consulting-project-template) | Estructura inicial para crear un repositorio independiente por proyecto, con sus áreas numeradas. |

## Contexto del sistema

![C4 nivel 1: contexto objetivo de AWS Cloud Consultant Agent](docs/c4-context.svg)

## 1. Proceso actual: del cliente al informe ejecutivo

El video muestra un proceso manual: cada persona prepara su parte y entrega
los insumos a la siguiente. La coordinación de reuniones, el traslado de
información y la recopilación de resultados dependen del equipo.

1. **Descubrimiento (Engagement Manager).** El cliente escribe por correo; el responsable comparte su agenda y confirma la reunión. Después recoge las necesidades, el presupuesto y los plazos, organiza sus notas y revisa proyectos anteriores para preparar la propuesta.

2. **Priorización (Executive Leadership).** El Engagement Manager presenta la propuesta y la dirección evalúa si continuar. Si la aprueba, prioriza el proyecto, autoriza el presupuesto de nube y pasa los insumos al arquitecto. Si la descarta, el proceso termina y el Engagement Manager informa al cliente que no se continuará con el proyecto.

3. **Diseño (Cloud Solutions Architect).** El arquitecto dibuja la solución AWS, selecciona los módulos de línea base y prepara una primera estimación. Entrega el diagrama, los recursos y los supuestos de uso a FinOps.

4. **Costos (FinOps Analyst).** Estima los costos de los recursos en AWS Pricing Calculator y prepara un Excel con el desglose, las proyecciones y los escenarios de costos. Contrasta ambos insumos con el presupuesto aprobado y entrega la estimación de la calculadora y el Excel validados a ingeniería.

5. **Implementación (Cloud Infrastructure Engineer).** Programa Terraform, revisa el código y ejecuta pruebas de configuración, seguridad y cumplimiento del diseño. Realiza el despliegue local, guarda las evidencias y prepara el plan de despliegue.

6. **Informe (Engagement Manager).** Recibe el proyecto y los resultados de ingeniería, reúne los documentos y los tiempos de cada etapa y entre entregas. Prepara el informe ejecutivo y lo presenta a dirección.

> **Resultado:** infraestructura validada localmente y preparada para desplegarse; el equipo de desarrollo puede continuar con la aplicación.

## 2. Video del proceso actual

https://github.com/user-attachments/assets/7f10b3d4-1c70-4ffb-8118-c16bec2319a3

## 3. Transformación propuesta con agentes de IA

La propuesta se define en [los issues de agentes](issues.md): incorpora apoyo de IA en cada etapa y conserva la revisión y las decisiones de las personas responsables. Cada entrega al siguiente equipo comparte el contexto del proyecto, los documentos y las aprobaciones, evitando volver a recopilar la misma información.

El diagrama se lee de izquierda a derecha. Cada columna muestra **proceso → puesto → agente → funcionalidad**. El agendamiento y la preparación usan agentes separados, al igual que el proyecto y los baselines. EM se refiere al Engagement Manager.

![Propuesta de transformación con agentes de IA: seis etapas, puestos responsables, agentes y funcionalidades](docs/process-flow.png)

## 4. Oficina virtual

El dashboard permite identificar la etapa del flujo de trabajo en la que se encuentra el agente y el equipo con el que colabora para ese proyecto.

![Vista de la oficina virtual con el agente en el área de Arquitectura](docs/live-dashboard.png)
