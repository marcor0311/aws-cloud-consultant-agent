"""Private STDIO tools and PDF resource for the Engagement Manager."""

import os
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.delivery.models import DemoRequest, ReportDecision
from app.delivery.review import ReportReview, configured_manager
from app.delivery.workflow import DeliveryWorkflow
from app.persistence.delivery import DeliveryBusy, DeliveryConflict, PostgresRepository


def pdf_uri(delivery_id, artifact_id):
    return f"delivery://pdf/{delivery_id}/{artifact_id}"


def create_server(repository: PostgresRepository, operator: str):
    server = MCPServer(
        "Informe ejecutivo PSWE-07",
        instructions=(
            "El informe utiliza datos de demostración. Mostrá versión y SHA-256 al "
            "Engagement Manager. Registrá aprobación o presentación únicamente si el "
            "operador lo confirma expresamente para esa revisión."
        ),
    )
    service = ReportReview(repository)

    def call(method, *args):
        try:
            result = method(*args)
        except (ValueError, LookupError, DeliveryBusy, DeliveryConflict) as error:
            raise ToolError(str(error)) from error
        if report := result["report"]:
            artifact = report.get("approved_document") or report["artifact"]
            result["pdf_uri"] = pdf_uri(result["delivery_id"], artifact["artifact_id"])
        return result

    @server.tool()
    def generar_informe(entrada: DemoRequest) -> dict:
        """Genera un informe de demostración desde los insumos de arquitectura y FinOps."""
        return call(DeliveryWorkflow(repository).run, entrada)

    @server.tool()
    def consultar_informe(entrega_id: UUID) -> dict:
        """Consulta el informe vigente, tiempos, historial y URI de descarga."""
        return call(service.get, entrega_id)

    @server.tool()
    def registrar_decision_informe(entrega_id: UUID, decision: ReportDecision) -> dict:
        """Solicita ajustes, guarda revisión, aprueba o registra una presentación confirmada."""
        return call(service.decide, entrega_id, decision, operator)

    @server.resource(
        "delivery://pdf/{entrega_id}/{archivo_id}", mime_type="application/pdf"
    )
    def informe_pdf(entrega_id: str, archivo_id: str) -> bytes:
        """Lee el PDF exacto asociado a la entrega, por identificador inmutable."""
        try:
            artifact = repository.artifact(UUID(entrega_id), UUID(archivo_id))
        except ValueError:
            raise ValueError("Identificador de entrega o archivo inválido") from None
        if not artifact or artifact["media_type"] != "application/pdf":
            raise ValueError("PDF no encontrado")
        return bytes(artifact["content"])

    return server


def main():
    dsn = os.getenv("DELIVERY_DATABASE_URL")
    if not dsn:
        raise SystemExit("Configurar DELIVERY_DATABASE_URL")
    create_server(PostgresRepository(dsn), configured_manager()).run(transport="stdio")


if __name__ == "__main__":
    main()
