"""Run one local worker; HTTP and MCP entry points never start this process."""

import logging
import threading
import time
import uuid

from app.integrations.errors import ProviderError


def serve(runtime, stopped):
    with runtime.worker_lock.hold():
        if runtime.settings.calendar_webhook_url:
            runtime.store.receive(
                f"calendar-startup:{uuid.uuid4()}",
                "calendar_sync",
                {"calendar_id": runtime.settings.calendar_id},
            )
        next_poll = next_maintenance = 0.0
        while not stopped.is_set():
            now = time.monotonic()
            try:
                runtime.deliver_post_calls()
                if now >= next_poll:
                    next_poll = now + 10
                    runtime.poll_google()
                if now >= next_maintenance:
                    next_maintenance = now + 60
                    runtime.maintenance()
                if not runtime.run_once():
                    stopped.wait(1)
            except ProviderError as error:
                logging.warning(
                    "Workflow provider needs configuration/retry: %s",
                    type(error).__name__,
                )
                stopped.wait(10)
            except Exception as error:
                logging.warning("Workflow worker needs retry: %s", type(error).__name__)
                stopped.wait(5)


def main():
    from app.bootstrap import create_access_service, create_runtime
    from app.core.config import load_environment
    from app.workflow.settings import WorkflowSettings

    load_environment()
    settings = WorkflowSettings.from_environment()
    if not settings.enabled:
        raise SystemExit("Configurar WORKFLOW_ENABLED=1 para iniciar el flujo.")
    runtime = create_runtime(
        settings, client_lookup=create_access_service().clients.lookup_code
    )
    try:
        serve(runtime, threading.Event())
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
