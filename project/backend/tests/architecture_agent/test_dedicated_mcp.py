"""The dedicated server exposes only the Cloud Architecture Agent boundary."""

from app.architecture.mcp_server import create_server, create_service


def test_dedicated_mcp_has_only_architecture_tools(tmp_path):
    service, resources = create_service(
        database_url=f"sqlite:///{tmp_path / 'workflow.sqlite3'}",
        checkpoint_path=tmp_path / "checkpoints.sqlite3",
    )
    try:
        tools = set(create_server(service)._tool_manager._tools)
        assert tools == {
            "consultar_catalogo_baselines",
            "leer_entrega_agente_2",
            "publicar_arquitectura_local",
            "iniciar_arquitectura",
            "consultar_arquitectura",
            "consultar_historial_arquitectura",
            "obtener_handoff_finops",
            "corregir_arquitectura",
            "revisar_arquitectura",
            "solicitar_correccion_finops",
            "aplicar_correccion_finops",
        }
    finally:
        resources.close()
