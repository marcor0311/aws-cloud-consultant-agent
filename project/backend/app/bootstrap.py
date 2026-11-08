"""Compose existing services and adapters for HTTP, MCP and the local worker."""

import os
import time
from contextlib import ExitStack
from pathlib import Path

from app.architecture.catalog import BaselineCatalog
from app.architecture.graph import build_graph as build_architecture_graph
from app.architecture.service import ArchitectureService
from app.clients.repository import ClientRepository
from app.core.config import project_path
from app.integrations.ai.preparer import OpenAIPreparer
from app.integrations.google_workspace import GoogleWorkspace
from app.integrations.langgraph import LangGraphExecution
from app.integrations.slack import SlackNotifier
from app.notifications.provider import EnvironmentMailer
from app.persistence.checkpoints import open_checkpointer
from app.persistence.locking import LocalWorkerLock
from app.persistence.workflow import WorkflowStore
from app.preparation.graph import build_graph
from app.preparation.references import REFERENCE_DIR, ReferenceCatalog
from app.preparation.service import PreparationService
from app.verification.repository import SQLiteVerificationRepository
from app.verification.service import CalendarAccessService
from app.workflow.graph import build_process_graph
from app.workflow.runtime import WorkflowRuntime
from app.workflow.service import ProcessService


def create_access_service():
    secret = os.getenv("CALENDAR_ACCESS_CODE_SECRET", "")
    if secret == os.getenv("CALENDAR_ACCESS_SERVICE_KEY", ""):
        raise ValueError("independent_access_keys_required")
    database = project_path(
        os.getenv("CALENDAR_ACCESS_DB", "data/calendar-access.sqlite3")
    )
    return CalendarAccessService(
        SQLiteVerificationRepository(database),
        secret,
        EnvironmentMailer(),
        ClientRepository(database),
    )


def create_runtime(
    settings,
    *,
    google=None,
    notifier=None,
    drafter=None,
    reference_dir=REFERENCE_DIR,
    clock=time.time,
    client_lookup=None,
    baseline_root=None,
):
    resources = ExitStack()
    try:
        mock_clock = None
        if settings.mode == "mock":
            if not settings.mock_dir:
                raise ValueError("El modo mock requiere su propio directorio de datos.")
            from app.integrations.mocks import MockClock

            mock_clock = MockClock(settings.mock_dir)
            clock = mock_clock
        store = WorkflowStore(settings.database_url, clock=clock)
        resources.callback(store.engine.dispose)
        store.import_references(reference_dir)
        saver = resources.enter_context(open_checkpointer(settings.checkpoint_url))
        references = ReferenceCatalog(store)
        if settings.mode == "mock":
            from app.integrations.mocks import MockPreparer, MockSlack, MockWorkspace

            google = google or MockWorkspace(store, settings.mock_dir)
            notifier = notifier or MockSlack(store, settings.manager_id)
            drafter = drafter or MockPreparer(references, store, mock_clock)
        else:
            google = google or GoogleWorkspace(settings.google_token_file)
            notifier = notifier or SlackNotifier(
                settings.slack_token, settings.slack_user_id
            )
            drafter = drafter or OpenAIPreparer(
                settings.openai_key,
                settings.openai_model,
                search=references.search,
                read=references.read_reference,
            )
        process = ProcessService(
            LangGraphExecution(build_process_graph(saver)), store, settings.manager_id
        )
        catalog = BaselineCatalog(
            baseline_root
            or Path(__file__).resolve().parents[4]
            / "aws-cloud-consultant-baseline-modules"
        )
        architecture = ArchitectureService(
            LangGraphExecution(build_architecture_graph(saver, catalog)),
            catalog,
            store,
            process,
            architect_id="cloud-solutions-architect",
        )
        service = PreparationService(
            LangGraphExecution(build_graph(saver, references.search, drafter, store)),
            store,
            settings.manager_id,
            on_sync=process.sync_preparation,
        )
        return WorkflowRuntime(
            settings,
            store=store,
            process=process,
            service=service,
            google=google,
            notifier=notifier,
            drafter=drafter,
            references=references,
            worker_lock=LocalWorkerLock(settings.database_url),
            resources=resources,
            architecture=architecture,
            mock_clock=mock_clock,
            client_lookup=client_lookup,
        )
    except BaseException:
        resources.close()
        raise
