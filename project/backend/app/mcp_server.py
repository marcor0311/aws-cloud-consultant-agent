"""Private single-operator STDIO entry point; never expose as unauthenticated HTTP."""

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.bootstrap import create_runtime
from app.core.config import PROJECT_DIR, load_environment
from app.integrations.errors import ProviderError
from app.integrations.opening_documents import OpeningDocuments
from app.persistence.workflow import Busy
from app.preparation.deliveries import PreparationDeliveries
from app.preparation.references import read_reference, search_references
from app.project_opening.models import ApprovedFile
from app.workflow.settings import WorkflowSettings


def create_server(service, runtime=None):
    server = MCPServer(
        "Agente de preparación",
        instructions=(
            "Para trabajar con Stuart, invoca primero agente_preparacion sin proyecto: "
            "muestra los proyectos y pregunta cuál quiere trabajar. Los borradores ya "
            "los prepara el agente antes de que Stuart llegue. Al elegir proyecto, "
            "presenta el resumen y la presentación, y ofrece mejorarlos. "
            "La primera aprobación genera el guion desde las diapositivas aprobadas. "
            "Antes de esa aprobación, vincula los cinco archivos exportados con registrar_archivos_presentacion. "
            "Después muestra el guion y solicita su aprobación expresa en la nueva revisión. "
            "Tras aprobar el guion, invoca exportar_paquete_aprobado para entregar seis archivos y su manifiesto. "
            "Para editar solo el guion usa actualizar_insumos con speaker_notes; "
            "tras solicitar ajustes al guion, usa guardar_guion_revisado. "
            "Guarda comentarios o cambios explícitos mediante las herramientas. "
            "Solo aprobar la revisión exacta tras una decisión expresa de Stuart; "
            "leer documentos o recibir Slack no constituye aprobación."
        ),
    )

    def call(method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except OSError:
            raise ToolError("No se pudo leer o exportar el archivo local.") from None
        except (ValueError, ProviderError, Busy) as error:
            raise ToolError(str(error)) from error

    @server.tool()
    def registrar_archivos_presentacion(
        expediente_id: str,
        revision: int,
        archivos: list[dict[str, str]],
        directorio: str = "",
    ) -> dict:
        """Vincula los cinco archivos locales antes de aprobar su presentación, sin aprobarlos."""
        call(service._owned, expediente_id)
        files = [ApprovedFile.model_validate(file) for file in archivos]
        documents = OpeningDocuments(
            directorio or PROJECT_DIR.parent / "insumos temporales de agente 1",
            PROJECT_DIR / "agents/2. meeting assistant/templates/architecture.md",
            service.store,
        )
        call(documents.validate, files)
        return call(
            PreparationDeliveries(service.store).stage,
            expediente_id,
            revision,
            archivos,
            source_directory=str(documents.source_dir),
        )

    @server.tool()
    def exportar_paquete_aprobado(
        expediente_id: str, revision: int, directorio: str = ""
    ) -> dict:
        """Exporta seis archivos aprobados por versión y registra sus hashes; no publica en GitHub."""
        call(service._owned, expediente_id)
        documents = OpeningDocuments(
            directorio or PROJECT_DIR.parent / "insumos temporales de agente 1",
            PROJECT_DIR / "agents/2. meeting assistant/templates/architecture.md",
            service.store,
        )
        return call(documents.export_preparation, expediente_id, revision)

    @server.tool()
    def iniciar_preparacion(
        expediente_id: str,
        evento_id: str,
        transcripcion: str,
        consulta: str,
        notas_reunion: str = "",
    ) -> dict:
        """Inicia con transcripción y notas opcionales separadas del operador; no consulta Meet."""
        if runtime:
            return call(
                runtime.submit_preparation,
                expediente_id,
                "start",
                event_id=evento_id,
                transcript=transcripcion,
                query=consulta,
                meeting_notes=notas_reunion,
            )
        return call(
            service.start,
            expediente_id,
            evento_id,
            transcripcion,
            consulta,
            meeting_notes=notas_reunion,
        )

    @server.tool()
    def consultar_preparacion(expediente_id: str) -> dict:
        """Lee transcripción, notas de reunión, referencias y tarea pendiente del expediente."""
        return call(service.get, expediente_id)

    @server.tool()
    def guardar_borrador(expediente_id: str, borrador: str) -> dict:
        """Guarda JSON ExecutivePackage (schema en la pausa), con speaker_notes vacío."""
        if not borrador.strip():
            raise ToolError("El borrador no puede estar vacío.")
        return call(service.resume, expediente_id, "draft_with_chatgpt", borrador)

    @server.tool()
    def guardar_guion_revisado(expediente_id: str, revision: int, guion: str) -> dict:
        """Tras ajustes solicitados al guion: guarda una nueva revisión, sin aprobarla."""
        if not guion.strip():
            raise ToolError("El guion no puede estar vacío.")
        return call(
            service.resume, expediente_id, "revise_speaker_notes", guion, revision
        )

    @server.tool()
    def revisar_preparacion(
        expediente_id: str, decision: str, comentarios: str = "", revision: int = 0
    ) -> dict:
        """Aprueba/revisa el subject pendiente: presentación primero, guion después."""
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
        return call(service.review, expediente_id, revision, decision, comentarios)

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
    load_environment()
    runtime = create_runtime(WorkflowSettings.from_environment())
    try:
        create_server(runtime.service, runtime).run(transport="stdio")
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
