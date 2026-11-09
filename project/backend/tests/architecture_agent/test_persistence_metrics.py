"""Block F persistence, recovery, metrics and FinOps acceptance."""

import json
import os
import sqlite3
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import ValidationError

from app.architecture.catalog import BaselineCatalog
from app.architecture.demo import DEFAULT_INPUT
from app.architecture.graph import build_graph
from app.architecture.metrics import FinOpsHandoffAcceptance
from app.architecture.service import ArchitectureService
from app.integrations.langgraph import LangGraphExecution
from app.persistence.checkpoints import open_checkpointer
from app.persistence.workflow import WorkflowStore

BASELINES = Path(__file__).resolve().parents[5] / "aws-cloud-consultant-baseline-modules"


class Clock:
    def __init__(self, value=1_800_000_000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def service_at(root, clock):
    connection = sqlite3.connect(root / "checkpoints.sqlite3", check_same_thread=False)
    store = WorkflowStore(
        f"sqlite:///{root / 'workflow.sqlite3'}",
        clock=clock,
    )
    catalog = BaselineCatalog(BASELINES)
    service = ArchitectureService(
        LangGraphExecution(build_graph(SqliteSaver(connection), catalog)),
        catalog,
        store,
    )
    return connection, store, service


def package():
    return json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))


def close(connection, store):
    store.engine.dispose()
    connection.close()


def test_metrics_and_finops_acceptance_survive_restart(tmp_path):
    clock = Clock()
    connection, store, service = service_at(tmp_path, clock)
    pending = service.start("case-f", "approved-input", package())["state"]
    clock.advance(10)
    approved = service.review(
        "case-f", 1, pending["artifact_sha256"], "approve"
    )["state"]
    store.record_interval(
        "measured-agent-work",
        "case-f",
        "stage-3",
        "architect",
        "agent",
        clock.value - 8,
        clock.value - 5,
    )

    before = service.metrics("case-f")
    assert before["lead_time_seconds"] == 10
    assert before["process_time_seconds"] == {
        "agent": 3,
        "human_decision": 10,
        "total_recorded_union": 10,
    }
    assert before["wait_time_seconds"] == 0
    assert before["rework_cycles"] == 0
    assert before["finops_handoffs"][0]["pending_acceptance"] is True

    clock.advance(5)
    receipt = {
        "contract_version": "1.0",
        "case_id": "case-f",
        "revision": 1,
        "artifact_sha256": approved["artifact_sha256"],
        "accepted_by": "finops-agent",
        "accepted_at": datetime.fromtimestamp(clock.value, timezone.utc).isoformat(),
        "status": "accepted",
        "finops_reference": "finops://case-f/evaluations/1",
    }
    assert service.accept_finops_handoff("case-f", receipt)["duplicate"] is False
    assert service.accept_finops_handoff("case-f", receipt)["duplicate"] is True
    close(connection, store)

    connection, store, restarted = service_at(tmp_path, clock)
    after = restarted.metrics("case-f")
    handoff = after["finops_handoffs"][0]
    assert handoff["pending_acceptance"] is False
    assert handoff["wait_seconds"] == 5
    assert store.list("architecture_finops_acceptance") == [
        FinOpsHandoffAcceptance.model_validate(receipt).model_dump(mode="json")
    ]
    assert restarted.history("case-f")["current_revision"] == 1
    close(connection, store)


def test_finops_acceptance_rejects_wrong_artifact_and_conflict(tmp_path):
    clock = Clock()
    connection, store, service = service_at(tmp_path, clock)
    pending = service.start("case-f", "approved-input", package())["state"]
    service.review("case-f", 1, pending["artifact_sha256"], "approve")
    receipt = {
        "case_id": "case-f",
        "revision": 1,
        "artifact_sha256": "0" * 64,
        "accepted_by": "finops-agent",
        "accepted_at": datetime.fromtimestamp(clock.value, timezone.utc).isoformat(),
        "finops_reference": "https://example.test/finops/1",
    }
    with pytest.raises(ValueError, match="artefacto vigente"):
        service.accept_finops_handoff("case-f", receipt)
    receipt["artifact_sha256"] = pending["artifact_sha256"]
    service.accept_finops_handoff("case-f", receipt)
    receipt["finops_reference"] = "finops://case-f/another-evaluation"
    with pytest.raises(ValueError, match="otra aceptación"):
        service.accept_finops_handoff("case-f", receipt)
    close(connection, store)


def test_finops_acceptance_requires_timezone_and_traceable_reference():
    payload = {
        "case_id": "case-f",
        "revision": 1,
        "artifact_sha256": "a" * 64,
        "accepted_by": "finops-agent",
        "accepted_at": "2026-11-08T12:00:00",
        "finops_reference": "free text",
    }
    with pytest.raises(ValidationError):
        FinOpsHandoffAcceptance.model_validate(payload)


@pytest.mark.skipif(
    not os.getenv("WORKFLOW_TEST_POSTGRES_URL"),
    reason="isolated PostgreSQL URL not configured",
)
def test_architecture_recovers_metrics_and_acceptance_from_postgres():
    """Real integration evidence only when an isolated PostgreSQL URL is supplied."""
    checkpoint_url = os.environ["WORKFLOW_TEST_POSTGRES_URL"]
    database_url = checkpoint_url.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
    case_id = f"architecture-postgres-{uuid.uuid4().hex}"

    def open_service():
        resources = ExitStack()
        store = WorkflowStore(database_url)
        resources.callback(store.engine.dispose)
        saver = resources.enter_context(open_checkpointer(checkpoint_url))
        catalog = BaselineCatalog(BASELINES)
        service = ArchitectureService(
            LangGraphExecution(build_graph(saver, catalog)), catalog, store
        )
        return resources, store, service

    resources, store, service = open_service()
    pending = service.start(case_id, "postgres-input", package())["state"]
    approved = service.review(
        case_id, 1, pending["artifact_sha256"], "approve"
    )["state"]
    receipt = {
        "case_id": case_id,
        "revision": 1,
        "artifact_sha256": approved["artifact_sha256"],
        "accepted_by": "finops-agent",
        "accepted_at": datetime.now(timezone.utc).isoformat(),
        "finops_reference": f"finops://{case_id}/evaluations/1",
    }
    service.accept_finops_handoff(case_id, receipt)
    resources.close()

    resources, store, restarted = open_service()
    try:
        assert restarted.history(case_id)["current_revision"] == 1
        assert restarted.accept_finops_handoff(case_id, receipt)["duplicate"] is True
        metrics = restarted.metrics(case_id)
        assert metrics["finops_handoffs"][0]["pending_acceptance"] is False
        assert store.list("architecture_finops_acceptance")
    finally:
        resources.close()
