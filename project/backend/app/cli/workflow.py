"""Run the durable worker or inspect configuration without printing credentials."""

import argparse
import json
import threading

from app.bootstrap import create_access_service, create_runtime
from app.core.config import load_environment
from app.worker import serve
from app.workflow.settings import WorkflowSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "status",
            "run",
            "once",
            "import-references",
            "calendar-watch",
            "calendar-sync",
            "meetings",
        ],
    )
    args = parser.parse_args()
    load_environment()
    settings = WorkflowSettings.from_environment()
    if args.command == "status":
        print(json.dumps(settings.availability(), indent=2))
        return
    if not settings.enabled and args.command != "import-references":
        parser.error("Configurar WORKFLOW_ENABLED=1 para iniciar el flujo.")
    lookup = (
        create_access_service().clients.lookup_code
        if args.command != "import-references"
        else None
    )
    runtime = create_runtime(settings, client_lookup=lookup)
    try:
        if args.command == "once":
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
        elif args.command == "import-references":
            print(
                json.dumps(
                    {"reference_documents": len(runtime.store.list("reference"))}
                )
            )
        else:
            serve(runtime, threading.Event())
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
