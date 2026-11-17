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
                "codigo_transcrito": "Charlie Uniform Uniform Hotel 0 0 1 2",
            },
        )
        assert not result.is_error
        payload = json.loads(result.content[0].text)
        assert payload["codigo_normalizado"] == "CUUH-0012"
        assert payload["estado"] == "pendiente_confirmacion"
        assert payload["respuesta_para_decir"] == (
            "Letras: Charlie, Uniform, Uniform, Hotel. "
            "Números: cero, cero, uno, dos. ¿Es correcto?"
        )
        # The caller repeats the code with a spoken separator; it remains the
        # same client identifier and still requires confirmation before OTP.
        repeated = await session.call_tool(
            "preparar_confirmacion_cliente",
            {
                "codigo_transcrito": "Charlie Uniform Uniform Hotel guión cero cero uno dos"
            },
        )
        assert not repeated.is_error
        assert json.loads(repeated.content[0].text) == payload
