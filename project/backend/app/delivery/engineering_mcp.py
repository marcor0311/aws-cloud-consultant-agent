"""Private STDIO entry for engineering intake, evidence import and measured status."""

import json
import os
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from app.core.config import load_environment, project_path
from app.delivery.engineering_models import (
    EngineeringEvidence,
    EngineeringIntake,
    EngineeringIntegration,
    EngineeringPublication,
    EngineeringRelease,
    FinOpsEngineeringReceipt,
)
from app.integrations.errors import ProviderError
from app.persistence.delivery import DeliveryConflict
from app.persistence.locking import Busy


def create_server(service, publication=None):
    server = MCPServer(
        "Ingeniería - recepción y evidencias",
        instructions="Registra entregas y resultados existentes. Publicar o integrar un PR requiere instrucción expresa del operador para la recepción exacta. Nunca emite una revisión como arquitecto; verifica su revisión real en GitHub. No ejecuta Terraform. Mostrá faltantes y procedencia de evidencias.",
    )

    def call(method, value):
        try:
            result = method(value)
        except (
            ValueError,
            LookupError,
            DeliveryConflict,
            Busy,
            ProviderError,
        ) as error:
            raise ToolError(str(error)) from error
        return CallToolResult(
            structured_content=result,
            content=[
                TextContent(type="text", text=json.dumps(result, ensure_ascii=False))
            ],
        )

    @server.tool()
    def recibir_entrega_finops(recepcion: FinOpsEngineeringReceipt) -> CallToolResult:
        """Recibe las publicaciones originales de #19/#20, conserva sus hashes y devuelve aceptación.

        Los módulos requieren referencias explícitas de aprobación; no se inventan.
        Sincroniza etapa 4 con la autorización FinOps existente, sin aprobar ingeniería.
        """
        return call(service.receive_finops, recepcion)

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

    @server.tool()
    def consultar_catalogo_compatibilidad(intake_id: UUID) -> CallToolResult:
        """Lista combinaciones declaradas, versiones, fallos y límites por recepción."""
        return call(service.catalog, intake_id)

    @server.tool()
    def registrar_entrega_tecnica(entrega: EngineeringRelease) -> CallToolResult:
        """Registra un PR ya integrado y verifica su aprobación exacta en el proceso.

        El operador confirma las referencias de GitHub y baselines; esta herramienta
        no abre, revisa ni integra PRs y no envía notificaciones externas.
        """
        return call(service.record_release, entrega)

    if publication is not None:

        @server.tool()
        def publicar_pr_ingenieria(solicitud: EngineeringPublication) -> CallToolResult:
            """Con autorización expresa, publica el commit probado y solicita revisión del arquitecto."""
            return call(publication.publish, solicitud)

        @server.tool()
        def integrar_pr_ingenieria(solicitud: EngineeringIntegration) -> CallToolResult:
            """Con autorización expresa, verifica revisión/CI/baselines, integra y encola aviso al EM."""
            return call(publication.integrate, solicitud)

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

    load_environment()
    runtime = create_engineering_runtime(
        os.getenv("WORKFLOW_DATABASE_URL", ""),
        project_path(
            os.getenv("ENGINEERING_ARTIFACTS_DIR", "generated/engineering-inputs")
        ),
        os.getenv("ENGINEERING_OPERATOR", ""),
        checkpoint_url=os.getenv("WORKFLOW_CHECKPOINT_URL") or None,
    )
    try:
        create_server(runtime.service, runtime.publication).run(transport="stdio")
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
