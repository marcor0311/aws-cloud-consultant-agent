"""Dedicated STDIO MCP server for the Cloud FinOps Agent."""

import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.finops.service import FinOpsService
from app.persistence.workflow import WorkflowStore

BACKEND = Path(__file__).resolve().parents[2]


def create_service(*, database_url: str | None = None):
    data = Path(os.environ.get("FINOPS_DATA_DIR", BACKEND / "data" / "finops-mcp"))
    data = data.resolve()
    data.mkdir(parents=True, exist_ok=True)
    shared_default = BACKEND / "data" / "architecture-mcp" / "workflow.sqlite3"
    database = database_url or os.environ.get(
        "FINOPS_DATABASE_URL",
        os.environ.get("ARCHITECTURE_DATABASE_URL", f"sqlite:///{shared_default}"),
    )
    if database.startswith("postgresql://"):
        database = database.replace("postgresql://", "postgresql+psycopg://", 1)
    resources = ExitStack()
    store = WorkflowStore(database)
    resources.callback(store.engine.dispose)
    return FinOpsService(store, output_dir=data / "artifacts"), resources


def create_server(service):
    server = MCPServer(
        "Cloud FinOps Agent",
        instructions=(
            "Recibe únicamente handoffs aprobados del agente de Arquitectura. "
            "No inventes precios, consumos, presupuestos, conversiones ni descuentos. "
            "Codex opera AWS Pricing Calculator y registra aquí su evidencia real. "
            "La recepción no es aprobación económica y una evaluación parcial no "
            "puede aprobarse. Devuelve las correcciones a Codex; no llames directamente "
            "al MCP de Arquitectura."
        ),
    )

    def call(method, *args):
        try:
            return method(*args)
        except ValueError as error:
            raise ToolError(str(error)) from error

    @server.tool()
    def recibir_handoff_arquitectura(
        expediente_id: str, handoff: dict[str, Any]
    ) -> dict[str, Any]:
        """Valida y recibe una revisión exacta; devuelve el recibo para Codex."""
        return call(service.receive_handoff, expediente_id, handoff)

    @server.tool()
    def consultar_recepcion_finops(expediente_id: str, revision: int) -> dict:
        """Consulta recepción, handoff persistido, evidencias y análisis vigente."""
        return call(service.intake_status, expediente_id, revision)

    @server.tool()
    def validar_issue_finops(
        expediente_id: str, revision: int, issue: dict[str, Any]
    ) -> dict[str, Any]:
        """Valida el issue GitHub observado contra el handoff y recibos aprobados."""
        return call(service.register_issue, expediente_id, revision, issue)

    @server.tool()
    def preparar_plan_calculadora(expediente_id: str, revision: int) -> dict:
        """Prepara parámetros para Codex sin consultar ni calcular precios."""
        return call(service.prepare_calculator, expediente_id, revision)

    @server.tool()
    def generar_estimacion_aws(
        expediente_id: str,
        revision: int,
        evidencia: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Prepara la ejecución para Codex o valida la evidencia real devuelta."""
        return call(
            service.generate_aws_estimate,
            expediente_id,
            revision,
            evidencia,
        )

    @server.tool()
    def registrar_evidencia_calculadora(
        expediente_id: str, revision: int, evidencia: dict[str, Any]
    ) -> dict:
        """Registra evidencia real que coincide con el plan y la arquitectura."""
        return call(service.register_evidence, expediente_id, revision, evidencia)

    @server.tool()
    def ejecutar_analisis_finops(expediente_id: str, revision: int) -> dict:
        """Calcula indicadores derivados solo desde evidencias verificadas."""
        return call(service.run_analysis, expediente_id, revision)

    @server.tool()
    def consultar_resultado_finops(expediente_id: str, revision: int) -> dict:
        """Consulta cobertura, presupuesto y resultado económico vigente."""
        return call(service.result, expediente_id, revision)

    @server.tool()
    def generar_excel_costos(expediente_id: str, revision: int) -> dict[str, Any]:
        """Genera un único forecast.xlsx versionado desde evidencia persistida."""
        return call(service.generate_workbook, expediente_id, revision)

    @server.tool()
    def preparar_comentario_finops(
        expediente_id: str, revision: int, solicitud: dict[str, Any]
    ) -> dict[str, Any]:
        """Prepara un comentario trazable; Codex decide si lo publica en GitHub."""
        return call(service.prepare_comment, expediente_id, revision, solicitud)

    @server.tool()
    def emitir_decision_finops(
        expediente_id: str, revision: int, decision: dict[str, Any]
    ) -> dict:
        """Registra una decisión autorizada, independiente del recibo del handoff."""
        return call(service.decide, expediente_id, revision, decision)

    @server.tool()
    def generar_solicitud_correccion_arquitectura(
        expediente_id: str, revision: int, solicitud: dict[str, Any]
    ) -> dict:
        """Devuelve a Codex una FinOpsCorrectionRequest compatible con Arquitectura."""
        return call(service.correction_request, expediente_id, revision, solicitud)

    @server.tool()
    def consultar_historial_finops(expediente_id: str, revision: int) -> dict:
        """Consulta recepción, plan, evidencias, análisis, decisiones y correcciones."""
        return call(service.history, expediente_id, revision)

    return server


def main():
    service, resources = create_service()
    try:
        create_server(service).run(transport="stdio")
    finally:
        resources.close()


if __name__ == "__main__":
    main()
