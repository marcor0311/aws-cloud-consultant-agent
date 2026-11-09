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
    baseline_root: Path = BASELINES,
):
    data = Path(
        os.environ.get("ARCHITECTURE_DATA_DIR", BACKEND / "data" / "architecture-mcp")
    ).resolve()
    data.mkdir(parents=True, exist_ok=True)
    resources = ExitStack()
    store = WorkflowStore(database_url or f"sqlite:///{data / 'workflow.sqlite3'}")
    resources.callback(store.engine.dispose)
    saver = resources.enter_context(
        open_checkpointer(str(checkpoint_path or data / "checkpoints.sqlite3"))
    )
    catalog = BaselineCatalog(baseline_root)
    service = ArchitectureService(
        LangGraphExecution(build_graph(saver, catalog)),
        catalog,
        store,
        architect_id="codex-cloud-architect",
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
    def obtener_handoff_finops(expediente_id: str, revision: int) -> dict:
        """Entrega a Codex el contrato económico aprobado de la revisión vigente."""
        return call(service.get_finops_handoff, expediente_id, revision)

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
