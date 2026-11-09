"""Actual MCP STDIO transport to the project's private GitHub opening server."""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.core.config import BACKEND_DIR


class OpeningMCPClient:
    def __init__(self, parameters=None, *, mock_board_case="", execution_id=""):
        arguments = ["-m", "app.cli.meeting_assistant", "mcp"]
        if mock_board_case:
            arguments += [
                "--mock-board-for-case",
                mock_board_case,
                "--live-execution-id",
                execution_id,
            ]
        self.parameters = parameters or StdioServerParameters(
            command=sys.executable,
            args=arguments,
            cwd=str(BACKEND_DIR),
            env={
                **os.environ,
                "LANGSMITH_TRACING": "false",
                "LANGCHAIN_TRACING_V2": "false",
            },
        )

    async def _exchange(self, name, arguments):
        async with stdio_client(self.parameters) as (reader, writer):
            async with ClientSession(
                reader, writer, read_timeout_seconds=600
            ) as session:
                initialized = await session.initialize()
                tools = (await session.list_tools()).tools
                tool = next((t for t in tools if t.name == "ejecutar_apertura"), None)
                if tool is None:
                    raise ValueError("El servidor MCP no expone ejecutar_apertura.")
                result = await session.call_tool(name, arguments)
                if result.is_error:
                    message = " ".join(
                        c.text for c in result.content if c.type == "text"
                    )
                    raise ValueError(message or "La operación MCP falló.")
                # The server returns native dicts; MCP may include both representations.
                value = result.structured_content
                if value is None:
                    value = json.loads(
                        next(c.text for c in result.content if c.type == "text")
                    )
                return {
                    "result": value,
                    "tool": tool.model_dump(mode="json", by_alias=True),
                    "server": initialized.server_info.model_dump(mode="json"),
                    "transport": "stdio",
                    "protocol_version": initialized.protocol_version,
                }

    def preflight(self, case_id):
        return self._run("verificar_apertura", {"expediente_id": case_id})

    def execute(self, name, arguments):
        if name != "ejecutar_apertura":
            raise ValueError("Herramienta fuera del alcance de esta ejecución.")
        return self._run(name, arguments)

    def _run(self, name, arguments):
        try:
            return asyncio.run(self._exchange(name, arguments))
        except Exception as group:
            if not hasattr(group, "exceptions"):
                raise
            errors = list(group.exceptions)
            while errors:
                error = errors.pop()
                if hasattr(error, "exceptions"):
                    errors.extend(error.exceptions)
                elif isinstance(error, ValueError):
                    raise ValueError("MCP: " + str(error)) from None
            raise ValueError(
                "No se pudo completar el intercambio MCP; revisar el servidor."
            ) from None
