"""Private STDIO entry for engineering intake, evidence import and measured status."""

import json
import os
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from app.core.config import project_path
from app.delivery.engineering_models import EngineeringEvidence, EngineeringIntake
from app.persistence.delivery import DeliveryConflict
from app.persistence.locking import Busy


def create_server(service):
    server = MCPServer(
        "Ingeniería - recepción y evidencias",
        instructions="Registra entregas y resultados existentes. No ejecuta Terraform, no abre PRs y no aprueba infraestructura. Mostrá los faltantes y la procedencia declarada de las evidencias.",
    )

    def call(method, value):
        try:
            result = method(value)
        except (ValueError, LookupError, DeliveryConflict, Busy) as error:
            raise ToolError(str(error)) from error
        return CallToolResult(
            structured_content=result,
            content=[
                TextContent(type="text", text=json.dumps(result, ensure_ascii=False))
            ],
        )

    @server.tool()
    def registrar_entrada_ingenieria(entrada: EngineeringIntake) -> CallToolResult:
        """Recibe archivos locales y verifica decisiones previas del expediente."""
        return call(service.register, entrada)

    @server.tool()
    def registrar_evidencias_ingenieria(
        evidencia: EngineeringEvidence,
    ) -> CallToolResult:
        """Importa resultados y mediciones de una corrida existente, sin ejecutarla."""
        return call(service.record_evidence, evidencia)

    @server.tool()
    def consultar_ingenieria(intake_id: UUID) -> CallToolResult:
        """Consulta entrada, resultados declarados, revisiones y tiempos de fase."""
        return call(service.get, intake_id)

    @server.resource(
        "engineering://artifact/{intake_id}/{file_sha256}",
        mime_type="application/octet-stream",
    )
    def archivo_ingenieria(intake_id: str, file_sha256: str) -> bytes:
        """Descarga los bytes registrados de un insumo o evidencia por su hash."""
        return service.read_file(UUID(intake_id), file_sha256)

    return server


def main():
    from app.bootstrap import create_engineering_runtime

    runtime = create_engineering_runtime(
        os.getenv("WORKFLOW_DATABASE_URL", ""),
        project_path(
            os.getenv("ENGINEERING_ARTIFACTS_DIR", "generated/engineering-inputs")
        ),
        os.getenv("ENGINEERING_OPERATOR", ""),
    )
    try:
        create_server(runtime.service).run(transport="stdio")
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
