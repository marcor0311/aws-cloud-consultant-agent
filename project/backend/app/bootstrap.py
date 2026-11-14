"""Compose existing services and adapters for HTTP, MCP and the local worker."""

import os
import time
from contextlib import ExitStack

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


def create_opening_runtime(
    database_url,
    source_dir,
    issue_template,
    *,
    github=None,
    allow_simulated_board=False,
    simulated_board_case="",
):
    """Agent 2 shares the workflow PostgreSQL database, not OTP or demo storage."""
    from types import SimpleNamespace

    from app.integrations.board_documents import board_documents
    from app.integrations.opening_documents import OpeningDocuments
    from app.integrations.project_github import ProjectGitHub
    from app.integrations.slack_board import SlackBoardPoll
    from app.persistence.board_votes import BoardRepository
    from app.persistence.project_opening import ProjectOpeningRepository
    from app.project_opening.board import BoardService
    from app.project_opening.graph import build_opening_graph
    from app.project_opening.service import OpeningService

    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError(
            "Meeting Assistant requiere WORKFLOW_DATABASE_URL de PostgreSQL."
        )
    resources = ExitStack()
    try:
        store = WorkflowStore(
            database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        )
        resources.callback(store.engine.dispose)
        checkpoint_url = database_url.replace(
            "postgresql+psycopg://", "postgresql://", 1
        )
        saver = resources.enter_context(open_checkpointer(checkpoint_url))
        repository = ProjectOpeningRepository(store)
        documents = OpeningDocuments(source_dir, issue_template, store)
        slack = SlackBoardPoll(os.getenv("SLACK_BOT_TOKEN", ""))
        resources.callback(slack.client.close)
        board = BoardService(
            BoardRepository(store), repository, slack, store.clock, board_documents
        )

        def board_gate(case_id):
            allow_mock_case = case_id == simulated_board_case
            if allow_mock_case and not repository.get(case_id)["is_fictitious"]:
                raise ValueError(
                    "La autorización de votos mock requiere un caso ficticio."
                )
            return board.require_approval(
                case_id, allow_simulated=allow_simulated_board or allow_mock_case
            )

        provider = github or ProjectGitHub()
        if github is None:
            resources.callback(provider.client.close)
        execution = LangGraphExecution(
            build_opening_graph(
                saver,
                repository,
                provider,
                documents.files,
                documents.issue,
                board_gate,
            )
        )
        service = OpeningService(repository, execution, documents.validate, board_gate)
        return SimpleNamespace(
            service=service, board=board, store=store, close=resources.close
        )
    except BaseException:
        resources.close()
        raise


def create_document_preparation_runtime(
    database_url, transcript, content, *, manager_id
):
    """Persist the local document workflow; its supplied draft never invokes a model."""
    from types import SimpleNamespace

    from app.preparation.deliveries import PreparationDeliveries
    from app.preparation.references import search_references

    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("La preparación documental requiere PostgreSQL.")
    content.validate_transcript(transcript)
    resources = ExitStack()
    try:
        store = WorkflowStore(
            database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        )
        resources.callback(store.engine.dispose)
        saver = resources.enter_context(
            open_checkpointer(
                database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            )
        )
        process = ProcessService(
            LangGraphExecution(build_process_graph(saver)), store, manager_id
        )

        def supplied_draft(state):
            if state["transcript"] != transcript.as_text():
                raise ValueError("La preparación pertenece a otra transcripción.")
            return content.executive_package(transcript)

        service = PreparationService(
            LangGraphExecution(
                build_graph(saver, search_references, supplied_draft, store)
            ),
            store,
            manager_id,
            on_sync=process.sync_preparation,
            direction_actor="meeting-assistant",
            notifications=False,
        )
        return SimpleNamespace(
            service=service,
            process=process,
            store=store,
            deliveries=PreparationDeliveries(store),
            close=resources.close,
        )
    except BaseException:
        resources.close()
        raise


def create_runtime(
    settings,
    *,
    google=None,
    notifier=None,
    drafter=None,
    reference_dir=REFERENCE_DIR,
    clock=time.time,
    client_lookup=None,
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
                allow_inference=settings.inference_enabled,
            )
        process = ProcessService(
            LangGraphExecution(build_process_graph(saver)), store, settings.manager_id
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
            mock_clock=mock_clock,
            client_lookup=client_lookup,
        )
    except BaseException:
        resources.close()
        raise
