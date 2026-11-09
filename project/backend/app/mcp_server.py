"""Private single-operator STDIO entry point; never expose as unauthenticated HTTP."""

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.architecture.models import ArchitecturePackage
from app.core.config import load_environment
from app.integrations.errors import ProviderError
from app.persistence.workflow import Busy
from app.preparation.references import read_reference, search_references
from app.workflow.settings import WorkflowSettings


def create_server(service, runtime=None):
    server = MCPServer(
        "Agente de preparación",
        instructions=(
            "Para trabajar con Stuart, invoca primero agente_preparacion sin proyecto: "
            "muestra los proyectos y pregunta cuál quiere trabajar. Los borradores ya "
            "los prepara el agente antes de que Stuart llegue. Al elegir proyecto, "
            "presenta el resumen, ideas de presentación y guion, y ofrece mejorarlos. "
            "Guarda comentarios o cambios explícitos mediante las herramientas. "
            "Solo aprobar la revisión exacta tras una decisión expresa de Stuart; "
            "leer documentos o recibir Slack no constituye aprobación."
        ),
    )

    def call(method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (ValueError, ProviderError, Busy) as error:
            raise ToolError(str(error)) from error

    @server.tool()
    def iniciar_preparacion(
        expediente_id: str, evento_id: str, transcripcion: str, consulta: str
    ) -> dict:
        """Inicia el flujo local con texto aportado por el operador; no consulta Meet."""
        if runtime:
            return call(
                runtime.submit_preparation,
                expediente_id,
                "start",
                event_id=evento_id,
                transcript=transcripcion,
                query=consulta,
            )
        return call(service.start, expediente_id, evento_id, transcripcion, consulta)

    @server.tool()
    def consultar_preparacion(expediente_id: str) -> dict:
        """Lee la transcripción, las referencias y la tarea pendiente del expediente."""
        return call(service.get, expediente_id)

    @server.tool()
    def guardar_borrador(expediente_id: str, borrador: str) -> dict:
        """Guarda el borrador elaborado en ChatGPT y pausa para revisión humana."""
        if not borrador.strip():
            raise ToolError("El borrador no puede estar vacío.")
        return call(service.resume, expediente_id, "draft_with_chatgpt", borrador)

    @server.tool()
    def revisar_preparacion(
        expediente_id: str, decision: str, comentarios: str = "", revision: int = 0
    ) -> dict:
        """Solo tras decisión expresa del manager: approve o revise con comentarios."""
        if decision not in {"approve", "revise"}:
            raise ToolError("Usar approve o revise.")
        if decision == "revise" and not comentarios.strip():
            raise ToolError("Indicar los ajustes solicitados.")
        if runtime:
            if decision == "revise":
                return call(
                    runtime.submit_preparation,
                    expediente_id,
                    "review",
                    revision=revision,
                    decision=decision,
                    feedback=comentarios,
                )
            return call(service.review, expediente_id, revision, decision, comentarios)
        return call(
            service.resume,
            expediente_id,
            "manager_review",
            {"decision": decision, "feedback": comentarios},
        )

    @server.tool()
    def buscar_referencias(consulta: str) -> list[dict]:
        """Busca briefs ficticios por palabras y devuelve evidencia y procedencia."""
        return runtime.search(consulta) if runtime else search_references(consulta)

    @server.tool()
    def consultar_referencia(proyecto_id: str) -> dict:
        """Lee el brief completo y arquitecturas ficticias antes de citar el caso."""
        return call(runtime.read_reference if runtime else read_reference, proyecto_id)

    @server.tool()
    def consultar_tiempos(expediente_id: str) -> dict:
        """Consulta tiempos parciales medidos; los no instrumentados aparecen nulos."""
        return call(service.metrics, expediente_id)

    if runtime:

        @server.tool()
        def consultar_catalogo_baselines() -> list[dict]:
            """Lista módulos Terraform reales, perfiles y estado de aprobación; no genera IaC."""
            return call(runtime.architecture.catalog_modules)

        @server.tool()
        def leer_entrega_agente_2(entrega: dict[str, Any]) -> dict:
            """Lee insumos aprobados desde un commit del repositorio del proyecto."""
            return call(runtime.architecture.read_project_handoff, entrega)

        @server.tool()
        def publicar_arquitectura_local(expediente_id: str) -> dict:
            """Publica la revisión aprobada localmente sin commit ni push."""
            return call(runtime.architecture.publish_to_project, expediente_id)

        @server.tool()
        def preparar_publicacion_github(expediente_id: str) -> dict:
            """Prepara rama, archivos y PR para ejecución externa mediante GitHub MCP."""
            return call(runtime.architecture.prepare_github_publication, expediente_id)

        @server.tool()
        def registrar_pull_request_github(
            expediente_id: str, recibo: dict[str, Any]
        ) -> dict:
            """Registra el commit y PR creados por Codex mediante GitHub MCP."""
            return call(
                runtime.architecture.register_github_pull_request,
                expediente_id,
                recibo,
            )

        @server.tool()
        def registrar_aprobacion_pr_github(
            expediente_id: str, recibo: dict[str, Any]
        ) -> dict:
            """Registra la aprobación y merge exactos del PR de Arquitectura."""
            return call(
                runtime.architecture.register_github_approval,
                expediente_id,
                recibo,
            )

        @server.tool()
        def preparar_issue_finops(
            expediente_id: str, responsable_github: str
        ) -> dict:
            """Prepara el issue FinOps después del merge aprobado."""
            return call(
                runtime.architecture.prepare_finops_issue,
                expediente_id,
                responsable_github,
            )

        @server.tool()
        def registrar_issue_finops_github(
            expediente_id: str, recibo: dict[str, Any]
        ) -> dict:
            """Registra el issue FinOps creado externamente por Codex."""
            return call(
                runtime.architecture.register_finops_issue,
                expediente_id,
                recibo,
            )

        @server.tool()
        def iniciar_arquitectura(
            expediente_id: str, entrada_id: str, propuesta: dict[str, Any]
        ) -> dict:
            """Valida una propuesta arquitectónica para revisión humana; no genera Terraform."""
            try:
                package = ArchitecturePackage.model_validate(propuesta)
            except ValueError as error:
                raise ToolError(str(error)) from None
            return call(
                runtime.architecture.start,
                expediente_id,
                entrada_id,
                package.model_dump(mode="json"),
            )

        @server.tool()
        def consultar_arquitectura(expediente_id: str) -> dict:
            """Consulta la revisión, documentos y decisión pendiente del diseño."""
            return call(runtime.architecture.get, expediente_id)

        @server.tool()
        def consultar_historial_arquitectura(expediente_id: str) -> dict:
            """Consulta revisiones, correcciones, aprobaciones y entregas."""
            return call(runtime.architecture.history, expediente_id)

        @server.tool()
        def obtener_handoff_finops(expediente_id: str, revision: int) -> dict:
            """Entrega a Codex el handoff aprobado para invocar posteriormente FinOps."""
            return call(
                runtime.architecture.get_finops_handoff,
                expediente_id,
                revision,
            )

        @server.tool()
        def solicitar_correccion_finops(
            expediente_id: str, solicitud: dict[str, Any]
        ) -> dict:
            """Registra una solicitud estructurada de corrección de FinOps."""
            return call(
                runtime.architecture.request_finops_correction,
                expediente_id,
                solicitud,
            )

        @server.tool()
        def aplicar_correccion_finops(
            expediente_id: str,
            solicitud_id: str,
            propuesta: dict[str, Any],
        ) -> dict:
            """Crea una revisión nueva enlazada con la corrección de FinOps."""
            return call(
                runtime.architecture.revise_from_finops,
                expediente_id,
                solicitud_id,
                propuesta,
            )

        @server.tool()
        def corregir_arquitectura(
            expediente_id: str, revision: int, propuesta: dict[str, Any]
        ) -> dict:
            """Crea una revisión nueva después de cambios solicitados por el arquitecto."""
            return call(
                runtime.architecture.replace, expediente_id, revision, propuesta
            )

        @server.tool()
        def revisar_arquitectura(
            expediente_id: str,
            revision: int,
            artifact_sha256: str,
            decision: str,
            comentarios: str = "",
        ) -> dict:
            """Aprueba o devuelve la revisión y hash exactos mediante decisión humana explícita."""
            return call(
                runtime.architecture.review,
                expediente_id,
                revision,
                artifact_sha256,
                decision,
                comentarios,
            )

        @server.tool()
        def agente_preparacion(proyecto_id: str = "") -> dict:
            """Entrada para Stuart: pregunta por el proyecto; al elegirlo, entrega sus insumos ya preparados."""
            return call(runtime.open_preparation, proyecto_id)

        @server.tool()
        def comenzar_revision(expediente_id: str, revision: int) -> dict:
            """Cuando Stuart decide trabajar: acepta la entrega y empieza su intervalo activo."""
            return call(service.begin_review, expediente_id, revision)

        @server.tool()
        def comentar_preparacion(
            expediente_id: str, revision: int, comentario: str
        ) -> dict:
            """Guarda una idea o pregunta de Stuart, sin aprobar ni regenerar los documentos."""
            return call(service.comment, expediente_id, revision, comentario)

        @server.tool()
        def actualizar_insumos(
            expediente_id: str,
            revision: int,
            cambios: dict[str, Any],
            comentario: str = "",
        ) -> dict:
            """Guarda secciones mejoradas en la conversación como nueva revisión pendiente de aprobación."""
            return call(
                service.update_package, expediente_id, revision, cambios, comentario
            )

        @server.tool()
        def aceptar_entrega(handoff_id: str) -> dict:
            """Registra aceptación explícita de una entrega asignada a este responsable."""
            return call(runtime.process.accept_delivery, handoff_id)

        @server.tool()
        def listar_expedientes() -> list[dict]:
            """Lista expedientes del Engagement Manager autenticado por el proceso local."""
            return runtime.owned_cases()

        @server.tool()
        def consultar_insumo(expediente_id: str, nombre: str, revision: int) -> dict:
            """Lee executive-summary.md, presentation.md o speaker-notes.md de una revisión."""
            return call(runtime.artifact, expediente_id, nombre, revision)

        @server.tool()
        def aceptar_etapa(expediente_id: str, etapa: int, issue_url: str = "") -> dict:
            """Registra aceptación de trabajo en etapas 1–6; nunca deduce PT del issue."""
            return call(runtime.process.accept_stage, expediente_id, etapa, issue_url)

        @server.tool()
        def iniciar_trabajo(
            expediente_id: str, etapa: str = "preparation", issue_url: str = ""
        ) -> dict:
            """Inicia o reanuda un intervalo humano activo; pausar cuando se deje de trabajar."""
            return call(runtime.process.start_work, expediente_id, etapa, issue_url)

        @server.tool()
        def pausar_trabajo(session_id: str) -> dict:
            """Cierra el intervalo activo del manager; reanudar con iniciar_trabajo."""
            return call(runtime.process.pause_work, session_id)

        @server.tool()
        def consultar_integraciones() -> dict:
            """Muestra disponibilidad de configuración sin devolver secretos."""
            return {
                "configuration": runtime.settings.availability(),
                "tasks": runtime.store.pending_jobs(),
            }

        @server.tool()
        def reintentar_tarea(tarea_id: str) -> dict:
            """Tras corregir configuración, reintenta un fallo; nunca un envío Slack incierto."""
            call(runtime.store.retry_job, tarea_id)
            return {"status": "pending"}

        @server.tool()
        def reanudar_preparacion(expediente_id: str) -> dict:
            """Reanuda un nodo fallido con sus entradas persistidas, sin crear otro expediente."""
            return call(runtime.submit_preparation, expediente_id, "continue")

        @server.tool()
        def consultar_proceso(expediente_id: str) -> dict:
            """Lee etapa, iteración, versión e historial del workflow de seis etapas."""
            return call(runtime.process.get, expediente_id)

        @server.tool()
        def registrar_evento_proceso(
            expediente_id: str, evento: dict[str, Any]
        ) -> dict:
            """Registra una entrega o decisión humana explícita; requiere la versión exacta.

            Consultar primero consultar_proceso. Nunca inferir aprobación de un issue,
            de una lectura o de una respuesta del modelo. El worker aplica el evento.
            """
            from app.workflow.schemas import ProcessEvent

            try:
                payload = ProcessEvent.model_validate(evento).model_dump()
            except ValueError:
                raise ToolError(
                    "Evento de proceso inválido; revisar su contrato."
                ) from None
            return call(runtime.process.submit, expediente_id, payload)

    return server


def main():
    from app.bootstrap import create_runtime

    load_environment()
    runtime = create_runtime(WorkflowSettings.from_environment())
    try:
        create_server(runtime.service, runtime).run(transport="stdio")
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
