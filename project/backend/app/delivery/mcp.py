"""Private STDIO tools and PDF resource for the Engagement Manager."""

import json
import os
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from app.delivery.models import CaseReportRequest, DemoRequest, ReportDecision
from app.delivery.review import ReportReview, configured_manager
from app.delivery.workflow import DeliveryWorkflow
from app.persistence.delivery import DeliveryBusy, DeliveryConflict, PostgresRepository
from app.persistence.locking import Busy


def pdf_uri(delivery_id, artifact_id):
    return f"delivery://pdf/{delivery_id}/{artifact_id}"


def create_server(repository: PostgresRepository, operator: str, case_service=None):
    if case_service is not None and case_service.operator != operator:
        raise ValueError("El servicio de informes pertenece a otro operador")
    server = MCPServer(
        "Informe ejecutivo PSWE-07",
        instructions=(
            "El informe distingue expedientes, faltantes y datos de demostración. Mostrá versión y SHA-256 al "
            "Engagement Manager. Registrá aprobación o presentación únicamente si el "
            "operador lo confirma expresamente para esa revisión."
        ),
    )
    service = ReportReview(repository, operator, case_service)

    def call(method, *args):
        try:
            result = method(*args)
        except (ValueError, LookupError, DeliveryBusy, DeliveryConflict, Busy) as error:
            raise ToolError(str(error)) from error
        if report := result.get("report"):
            artifact = report.get("approved_document") or report["artifact"]
            result["pdf_uri"] = pdf_uri(result["delivery_id"], artifact["artifact_id"])
            if source := report.get("sources"):
                result["sources_uri"] = (
                    f"delivery://sources/{result['delivery_id']}/{source['artifact_id']}"
                )
        data = jsonable_encoder(result)
        return CallToolResult(
            structured_content=data,
            content=[
                TextContent(type="text", text=json.dumps(data, ensure_ascii=False))
            ],
        )

    @server.tool()
    def generar_informe(entrada: CaseReportRequest | DemoRequest) -> CallToolResult:
        """Con report_id y case_id consolida un expediente sin ejecutar ingeniería.

        intake_id adjunta una recepción y sus evidencias importadas. También se
        conserva engineering_delivery_id para la entrega de demostración. La entrada
        anterior con mode=demo conserva exclusivamente el recorrido de demostración.
        """
        if isinstance(entrada, CaseReportRequest):
            if case_service is None:
                raise ToolError(
                    "Configurar WORKFLOW_DATABASE_URL para consultar expedientes"
                )
            return call(case_service.generate, entrada)
        return call(DeliveryWorkflow(repository).run, entrada)

    @server.tool()
    def listar_expedientes_informe() -> CallToolResult:
        """Lista los expedientes del operador para preparar un informe."""
        if case_service is None:
            raise ToolError(
                "Configurar WORKFLOW_DATABASE_URL para consultar expedientes"
            )
        return call(
            lambda: {"projects": case_service.sources.store.project_list(operator)}
        )

    @server.tool()
    def consultar_informe(entrega_id: UUID) -> CallToolResult:
        """Consulta el informe vigente, tiempos, historial y URI de descarga."""
        return call(service.get, entrega_id)

    @server.tool()
    def registrar_decision_informe(
        entrega_id: UUID, decision: ReportDecision
    ) -> CallToolResult:
        """Solicita ajustes, guarda revisión, aprueba o registra una presentación confirmada."""
        return call(service.decide, entrega_id, decision, operator)

    @server.resource(
        "delivery://pdf/{entrega_id}/{archivo_id}", mime_type="application/pdf"
    )
    def informe_pdf(entrega_id: str, archivo_id: str) -> bytes:
        """Lee el PDF exacto asociado a la entrega, por identificador inmutable."""
        return read_artifact(entrega_id, archivo_id, "application/pdf")

    @server.resource(
        "delivery://sources/{entrega_id}/{archivo_id}", mime_type="application/json"
    )
    def fuentes_informe(entrega_id: str, archivo_id: str) -> bytes:
        """Descarga la instantánea con fuentes y mediciones que respaldan el PDF."""
        return read_artifact(entrega_id, archivo_id, "application/json")

    @server.resource(
        "delivery://engineering/{entrega_id}/{file_sha256}",
        mime_type="application/octet-stream",
    )
    def respaldo_ingenieria(entrega_id: str, file_sha256: str) -> bytes:
        """Descarga un respaldo incluido en la instantánea de fuentes del informe."""
        if case_service is None:
            raise ValueError("El lector de expedientes no está configurado")
        return case_service.read_engineering_file(UUID(entrega_id), file_sha256)

    def read_artifact(entrega_id, archivo_id, media_type):
        from app.delivery.report import require_report_owner

        try:
            delivery_id, artifact_id = UUID(entrega_id), UUID(archivo_id)
        except ValueError:
            raise ValueError("Identificador de entrega o archivo inválido") from None
        row = repository.get(delivery_id)
        if row:
            require_report_owner(row, operator)
        artifact = repository.artifact(delivery_id, artifact_id)
        if not artifact or artifact["media_type"] != media_type:
            raise ValueError("Archivo no encontrado")
        return bytes(artifact["content"])

    return server


def main():
    dsn = os.getenv("DELIVERY_DATABASE_URL")
    if not dsn:
        raise SystemExit("Configurar DELIVERY_DATABASE_URL")
    from app.bootstrap import create_report_runtime

    runtime = create_report_runtime(
        dsn, os.getenv("WORKFLOW_DATABASE_URL"), configured_manager()
    )
    try:
        create_server(runtime.repository, runtime.operator, runtime.service).run(
            transport="stdio"
        )
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
