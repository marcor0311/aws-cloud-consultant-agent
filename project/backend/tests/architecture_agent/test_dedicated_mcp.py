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
            "iniciar_arquitectura",
            "consultar_arquitectura",
            "corregir_arquitectura",
            "revisar_arquitectura",
        }
    finally:
        resources.close()
