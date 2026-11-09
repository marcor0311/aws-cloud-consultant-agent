"""Actual agent 1 MCP handshake and tool invocation, offline."""

import json

from src import agent


async def test_mcp_subprocess_starts_from_the_agent_root():
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.tools.calendar_mcp"],
        cwd=str(agent.PROJECT_DIR),
    )
    async with (
        stdio_client(parameters) as (reader, writer),
        ClientSession(reader, writer) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
        names = {tool.name for tool in listed.tools}
        assert names == {
            "preparar_confirmacion_cliente",
            "iniciar_verificacion_cliente",
            "validar_codigo_correo",
            "reenviar_codigo_correo",
            "consultar_horarios",
            "agendar_reunion",
            "buscar_reuniones",
            "reagendar_reunion",
            "cancelar_reunion",
        }
        result = await session.call_tool(
            "preparar_confirmacion_cliente",
            {
                "codigo_transcrito": "India Oscar Alfa Alfa cero cero uno dos",
            },
        )
        assert not result.is_error
        payload = json.loads(result.content[0].text)
        assert payload["codigo_normalizado"] == "IOAA-0012"
