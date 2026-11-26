"""Run the durable worker or inspect configuration without printing credentials."""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.bootstrap import create_access_service, create_runtime
from app.core.config import BACKEND_DIR, load_environment
from app.worker import serve
from app.workflow.settings import WorkflowSettings


async def query_preparation(project_id=""):
    """Call the actual MCP tool over STDIO; a query never starts the worker."""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        cwd=str(BACKEND_DIR),
        env={
            **os.environ,
            "WORKFLOW_INFERENCE_ENABLED": "0",
            "LANGSMITH_TRACING": "false",
            "LANGCHAIN_TRACING_V2": "false",
        },
    )
    with tempfile.TemporaryFile(mode="w+") as errors:
        async with stdio_client(parameters, errlog=errors) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.call_tool("prepare", {"proyecto_id": project_id})
                if result.is_error:
                    raise ValueError("El MCP no pudo consultar el proyecto solicitado.")
                if result.structured_content is not None:
                    return result.structured_content
                return json.loads(
                    next(c.text for c in result.content if c.type == "text")
                )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "status",
            "run",
            "once",
            "calendar-watch",
            "calendar-sync",
            "meetings",
            "preparation-start",
            "preparation-render",
            "prepare",
        ],
    )
    parser.add_argument("--case")
    parser.add_argument("--event")
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--meeting-notes", type=Path)
    parser.add_argument("--query")
    parser.add_argument("--revision", type=int)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        try:
            result = asyncio.run(
                asyncio.wait_for(query_preparation(args.case or ""), timeout=30)
            )
        except Exception:
            parser.exit(
                1,
                "No se pudo consultar el MCP local; revisá la configuración y PostgreSQL.\n",
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "preparation-start" and not all(
        (args.case, args.event, args.transcript, args.query)
    ):
        parser.error(
            "preparation-start requiere --case, --event, --transcript y --query."
        )
    if args.command == "preparation-render" and not (args.case and args.revision):
        parser.error("preparation-render requiere --case y --revision.")
    load_environment()
    settings = WorkflowSettings.from_environment()
    if args.command == "status":
        print(json.dumps(settings.availability(), indent=2))
        return
    if not settings.enabled:
        parser.error("Configurar WORKFLOW_ENABLED=1 para iniciar el flujo.")
    lookup = (
        create_access_service().clients.lookup_code
        if args.command not in {"preparation-start", "preparation-render"}
        else None
    )
    runtime = create_runtime(settings, client_lookup=lookup)
    try:
        if args.command == "preparation-render":
            state = runtime.service.get(args.case)["state"]
            runtime.service.update_package(
                args.case,
                args.revision,
                {"title": state["package"]["title"]},
                "Reexportación con las plantillas corporativas, sin nueva inferencia.",
                republish=True,
            )
            print(
                json.dumps(
                    runtime.open_preparation(args.case), ensure_ascii=False, indent=2
                )
            )
        elif args.command == "preparation-start":
            print(
                json.dumps(
                    runtime.submit_preparation(
                        args.case,
                        "start",
                        event_id=args.event,
                        transcript=args.transcript.read_text(encoding="utf-8"),
                        query=args.query,
                        meeting_notes=args.meeting_notes.read_text(encoding="utf-8")
                        if args.meeting_notes
                        else "",
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "once":
            runtime.deliver_post_calls()
            runtime.run_once()
        elif args.command == "calendar-watch":
            from app.workflow.calendar_sync import CalendarSync

            print(json.dumps(CalendarSync(runtime).subscribe()))
        elif args.command == "calendar-sync":
            from app.workflow.calendar_sync import CalendarSync

            CalendarSync(runtime).sync(settings.calendar_id)
            print(json.dumps({"status": "synchronized"}))
        elif args.command == "meetings":
            print(
                json.dumps(runtime.store.list("meeting"), indent=2, ensure_ascii=False)
            )
        else:
            serve(runtime, threading.Event())
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
