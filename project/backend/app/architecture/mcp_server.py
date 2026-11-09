"""Dedicated offline STDIO MCP server for the Cloud Architecture Agent."""

import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.architecture.catalog import BaselineCatalog
from app.architecture.graph import build_graph
from app.architecture.models import ArchitecturePackage
from app.architecture.service import ArchitectureService
from app.integrations.langgraph import LangGraphExecution
from app.persistence.checkpoints import open_checkpointer
from app.persistence.workflow import WorkflowStore

BACKEND = Path(__file__).resolve().parents[2]
WORKSPACE = Path(__file__).resolve().parents[5]
BASELINES = WORKSPACE / "aws-cloud-consultant-baseline-modules"


def create_service(
    *,
    database_url: str | None = None,
    checkpoint_path: Path | None = None,
    checkpoint_url: str | None = None,
    baseline_root: Path = BASELINES,
):
    data = Path(
        os.environ.get("ARCHITECTURE_DATA_DIR", BACKEND / "data" / "architecture-mcp")
    ).resolve()
    data.mkdir(parents=True, exist_ok=True)
    resources = ExitStack()
    database = database_url or os.environ.get(
        "ARCHITECTURE_DATABASE_URL", f"sqlite:///{data / 'workflow.sqlite3'}"
    )
    if database.startswith("postgresql://"):
        database = database.replace("postgresql://", "postgresql+psycopg://", 1)
    store = WorkflowStore(database)
    resources.callback(store.engine.dispose)
    configured_checkpoint = checkpoint_url or os.environ.get(
        "ARCHITECTURE_CHECKPOINT_URL", ""
    )
    if not configured_checkpoint:
        configured_checkpoint = (
            str(checkpoint_path)
            if checkpoint_path
            else (
                database.replace("postgresql+psycopg://", "postgresql://", 1)
                if database.startswith("postgresql+")
                else str(data / "checkpoints.sqlite3")
            )
        )
    saver = resources.enter_context(
        open_checkpointer(configured_checkpoint)
    )
    catalog = BaselineCatalog(baseline_root)
    service = ArchitectureService(
        LangGraphExecution(build_graph(saver, catalog)),
        catalog,
        store,
        architect_id="codex-cloud-architect",
        github_required=True,
    )
    return service, resources


def create_server(service):
    server = MCPServer(
        "Cloud Architecture Agent",
        instructions=(
            "Consulta primero consultar_catalogo_baselines. Construye la propuesta "
            "solo con requisitos y evidencia disponibles; registra preguntas para "
            "datos faltantes y nunca inventes aprobación, precios, commits o recursos. "
            "No generes Terraform. Presenta la revisión al arquitecto y llama "
            "revisar_arquitectura únicamente después de su decisión explícita."
        ),
    )

    def call(method, *args):
        try:
            return method(*args)
        except ValueError as error:
            raise ToolError(str(error)) from error

    @server.tool()
    def consultar_catalogo_baselines() -> list[dict]:
        """Lista módulos reales, perfiles, versiones y estado de aprobación."""
        return call(service.catalog_modules)

    @server.tool()
    def leer_entrega_agente_2(entrega: dict[str, Any]) -> dict:
        """Lee insumos aprobados desde un commit de un repo creado del template."""
        return call(service.read_project_handoff, entrega)

    @server.tool()
    def publicar_arquitectura_local(expediente_id: str) -> dict:
        """Publica la revisión aprobada bajo docs/03-architecture sin hacer commit."""
        return call(service.publish_to_project, expediente_id)

    @server.tool()
    def preparar_publicacion_github(expediente_id: str) -> dict:
        """Prepara archivos, rama y PR para que Codex invoque GitHub MCP."""
        return call(service.prepare_github_publication, expediente_id)

    @server.tool()
    def registrar_pull_request_github(expediente_id: str, recibo: dict[str, Any]) -> dict:
        """Registra el commit y PR creados externamente por Codex mediante GitHub MCP."""
        return call(service.register_github_pull_request, expediente_id, recibo)

    @server.tool()
    def registrar_aprobacion_pr_github(
        expediente_id: str, recibo: dict[str, Any]
    ) -> dict:
        """Registra aprobación y merge del PR y libera el handoff vigente."""
        return call(service.register_github_approval, expediente_id, recibo)

    @server.tool()
    def preparar_issue_finops(expediente_id: str, responsable_github: str) -> dict:
        """Prepara el issue FinOps después de la aprobación y merge de Arquitectura."""
        return call(service.prepare_finops_issue, expediente_id, responsable_github)

    @server.tool()
    def registrar_issue_finops_github(
        expediente_id: str, recibo: dict[str, Any]
    ) -> dict:
        """Registra el issue FinOps creado externamente mediante GitHub MCP."""
        return call(service.register_finops_issue, expediente_id, recibo)

    @server.tool()
    def iniciar_arquitectura(
        expediente_id: str, entrada_id: str, propuesta: dict[str, Any]
    ) -> dict:
        """Valida y persiste una propuesta para revisión; no genera Terraform."""
        try:
            package = ArchitecturePackage.model_validate(propuesta)
        except ValueError as error:
            raise ToolError(str(error)) from None
        return call(
            service.start,
            expediente_id,
            entrada_id,
            package.model_dump(mode="json"),
        )

    @server.tool()
    def consultar_arquitectura(expediente_id: str) -> dict:
        """Lee la revisión y decisión pendiente de un diseño persistido."""
        return call(service.get, expediente_id)

    @server.tool()
    def consultar_historial_arquitectura(expediente_id: str) -> dict:
        """Consulta revisiones, correcciones, aprobaciones y handoffs inmutables."""
        return call(service.history, expediente_id)

    @server.tool()
    def consultar_metricas_arquitectura(expediente_id: str) -> dict:
        """Consulta Lead Time, Process Time, esperas, retrabajo y handoffs."""
        return call(service.metrics, expediente_id)

    @server.tool()
    def obtener_handoff_finops(expediente_id: str, revision: int) -> dict:
        """Entrega a Codex el contrato económico aprobado de la revisión vigente."""
        return call(service.get_finops_handoff, expediente_id, revision)

    @server.tool()
    def registrar_aceptacion_handoff_finops(
        expediente_id: str, recibo: dict[str, Any]
    ) -> dict:
        """Registra el recibo tipado devuelto por el MCP de FinOps vía Codex."""
        return call(service.accept_finops_handoff, expediente_id, recibo)

    @server.tool()
    def solicitar_correccion_finops(
        expediente_id: str, solicitud: dict[str, Any]
    ) -> dict:
        """Reabre una entrega exacta mediante una solicitud estructurada de FinOps."""
        return call(service.request_finops_correction, expediente_id, solicitud)

    @server.tool()
    def aplicar_correccion_finops(
        expediente_id: str, solicitud_id: str, propuesta: dict[str, Any]
    ) -> dict:
        """Crea una revisión nueva vinculada a la corrección de FinOps."""
        return call(
            service.revise_from_finops,
            expediente_id,
            solicitud_id,
            propuesta,
        )

    @server.tool()
    def corregir_arquitectura(
        expediente_id: str, revision: int, propuesta: dict[str, Any]
    ) -> dict:
        """Crea una nueva revisión después de cambios solicitados."""
        return call(service.replace, expediente_id, revision, propuesta)

    @server.tool()
    def revisar_arquitectura(
        expediente_id: str,
        revision: int,
        artifact_sha256: str,
        decision: str,
        comentarios: str = "",
    ) -> dict:
        """Registra approve o revise para la revisión y SHA-256 exactos."""
        return call(
            service.review,
            expediente_id,
            revision,
            artifact_sha256,
            decision,
            comentarios,
        )

    return server


def main():
    service, resources = create_service()
    try:
        create_server(service).run(transport="stdio")
    finally:
        resources.close()


if __name__ == "__main__":
    main()
