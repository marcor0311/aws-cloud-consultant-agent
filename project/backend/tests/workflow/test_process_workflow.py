"""Six-stage lifecycle: durable pauses, exact approvals, rework and event replay."""

import sqlite3

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import ValidationError

from app.integrations.langgraph import LangGraphExecution
from app.persistence.locking import LocalWorkerLock
from app.persistence.workflow import Busy, WorkflowStore
from app.workflow.graph import build_process_graph
from app.workflow.schemas import ProcessEvent
from app.workflow.service import ProcessService
from app.workflow.state import STAGES
from app.workflow.transitions import transition

DIGEST = "a" * 64


def open_process(directory):
    store = WorkflowStore(f"sqlite:///{directory / 'business.sqlite3'}")
    connection = sqlite3.connect(
        directory / "checkpoints.sqlite3", check_same_thread=False
    )
    service = ProcessService(
        LangGraphExecution(build_process_graph(SqliteSaver(connection))),
        store,
        "stuart",
    )
    return service, connection


@pytest.fixture
def process(tmp_path):
    service, connection = open_process(tmp_path)
    service.store.put(
        "owner:case", "owner", {"manager_id": "stuart", "case_id": "case"}
    )
    service.ensure("case", client_id=42)
    try:
        yield service
    finally:
        connection.close()
        service.store.engine.dispose()


def payload(service, kind, event_id, **extra):
    state = service.get("case")["state"]
    return ProcessEvent(
        event_id=event_id,
        kind=kind,
        stage=state["stage"],
        iteration=state["iteration"],
        revision=state["revision"],
        artifact_sha256=state["artifact_sha256"],
        **extra,
    ).model_dump()


def deliver(service, stage, revision=1):
    state = service.get("case")["state"]
    data = ProcessEvent(
        event_id=f"deliver-{stage}-{state['iteration']}-{revision}",
        kind="deliverable.ready",
        stage=stage,
        iteration=state["iteration"],
        revision=revision,
        artifact_sha256=DIGEST,
        evidence=[f"repo/commit-{stage}/documents"],
    ).model_dump()
    return apply_operator(service, data)


def apply_operator(service, data):
    received = service.submit("case", data)
    job = service.store.job(received["task_id"])
    result = service.apply("case", job["payload"]["event"])
    service.store.finish_job(job["id"])
    return result


def direction_ready(service):
    service.internal("case", "transcript-1", "transcript.available")
    artifact = dict(revision=1, artifact_sha256=DIGEST, evidence=["artifact:case:1"])
    service.internal("case", "package-1", "preparation.ready", **artifact)
    service.internal("case", "manager-approval-1", "preparation.approved", **artifact)


def test_booking_waits_for_transcript_and_never_guesses_approval(process):
    state = process.get("case")
    assert state["state"]["client_id"] == 42
    assert state["state"]["status"] == "awaiting_meeting"
    assert state["pending"][0]["action"] == "await_process_event"
    completed = payload(process, "meeting.completed", "human-meeting-ended")
    queued = process.submit("case", completed)
    assert queued["status"] == "pending"
    assert process.get("case")["state"]["status"] == "awaiting_meeting"
    event = process.store.job(queued["task_id"])["payload"]["event"]
    process.apply("case", event)
    assert process.get("case")["state"]["status"] == "awaiting_transcript"
    with pytest.raises(ValueError, match="estado actual"):
        process.submit("case", payload(process, "stage.approved", "premature"))
    with pytest.raises(ValueError, match="estado actual"):
        process.internal(
            "case",
            "invented-draft",
            "preparation.ready",
            revision=1,
            artifact_sha256=DIGEST,
            evidence=["artifact:case:1"],
        )


def test_six_stages_rework_to_architecture_and_final_human_approval(process):
    direction_ready(process)
    assert process.get("case")["state"]["stage"] == 2
    apply_operator(process, payload(process, "stage.approved", "board-approved"))
    deliver(process, 3)
    architecture_approval = payload(process, "stage.approved", "architect-approved")
    apply_operator(process, architecture_approval)
    deliver(process, 4)
    apply_operator(
        process,
        payload(
            process,
            "stage.changes_requested",
            "finops-return",
            comment="La estimación supera el presupuesto.",
        ),
    )
    returned = process.get("case")["state"]
    assert returned["stage"] == 3 and returned["status"] == "awaiting_deliverable"
    assert returned["rework_cycles"] == 1
    # An old approval cannot approve the next visit to architecture.
    stale = {**architecture_approval, "event_id": "late-architect-approval"}
    with pytest.raises(ValueError, match="iteración cambió"):
        process.submit("case", stale)
    for stage in (3, 4, 5, 6):
        deliver(process, stage)
        before = process.get("case")["state"]
        apply_operator(
            process,
            payload(
                process, "stage.approved", f"approved-{stage}-{before['iteration']}"
            ),
        )
    final = process.get("case")
    assert final["state"]["status"] == "completed"
    assert final["pending"] == []
    assert len(process.store.case_handoffs("case")) == 6
    assert process.store.get("process:case")["rework_cycles"] == 1


def test_duplicate_events_survive_restart_and_conflicting_replays_are_rejected(
    process, tmp_path
):
    direction_ready(process)
    event = payload(process, "stage.approved", "approval-stable-id")
    apply_operator(process, event)
    previous = process.get("case")
    restarted, connection = open_process(tmp_path)
    try:
        assert restarted.get("case") == previous
        assert restarted.submit("case", event)["status"] == "duplicate"
        assert restarted.get("case") == previous
        with pytest.raises(ValueError, match="otro contenido"):
            restarted.submit("case", {**event, "comment": "changed after approval"})
        assert len(restarted.store.case_handoffs("case")) == 1
    finally:
        connection.close()
        restarted.store.engine.dispose()


def test_worker_revalidates_queued_approval_after_a_new_version(process):
    direction_ready(process)
    old = payload(process, "stage.approved", "queued-old-approval")
    task = process.submit("case", old)
    deliver(process, 2, revision=2)
    job = process.store.job(task["task_id"])
    with pytest.raises(ValueError, match="versión pendiente exacta"):
        process.apply("case", job["payload"]["event"])
    state = process.get("case")["state"]
    assert state["stage"] == 2 and state["revision"] == 2
    assert "queued-old-approval" not in state["processed"]


def test_recovery_after_event_checkpoint_before_next_pause_does_not_apply_twice(
    process,
):
    direction_ready(process)
    data = payload(process, "stage.approved", "crashed-after-checkpoint")
    receipt = process.submit("case", data)
    event = process.store.job(receipt["task_id"])["payload"]["event"]
    state = process.get("case")["state"]
    committed = transition(state, {**event, "at": process.store.clock()})
    process.graph.update(process.thread_id("case"), committed, after_step=STAGES[2])
    recovered = process.apply("case", event)
    assert recovered["state"]["stage"] == 3
    assert recovered["pending"][0]["stage"] == 3
    assert len(process.store.case_handoffs("case")) == 1
    deliver(process, 3)
    assert process.get("case")["state"]["status"] == "awaiting_review"


def test_direction_rejection_stops_the_graph(process):
    direction_ready(process)
    apply_operator(
        process,
        payload(
            process,
            "stage.rejected",
            "board-declined",
            comment="No continuar este proyecto.",
        ),
    )
    assert process.get("case")["state"]["status"] == "declined"
    assert process.get("case")["pending"] == []
    with pytest.raises(ValueError, match="terminó"):
        process.submit("case", payload(process, "stage.approved", "too-late"))


def test_cancelled_meeting_never_reaches_preparation(process):
    process.internal("case", "meeting.cancelled", "meeting.cancelled")
    assert process.get("case")["state"]["status"] == "cancelled"
    assert process.get("case")["pending"] == []
    process.internal("case", "meeting.cancelled", "meeting.cancelled")
    with pytest.raises(ValueError, match="terminó"):
        process.internal("case", "late-transcript", "transcript.available")


def test_internal_events_and_other_owners_are_not_accepted_from_operator(process):
    with pytest.raises(ValidationError):
        ProcessEvent(event_id="fake", kind="preparation.approved", stage=1, iteration=1)
    with pytest.raises(ValidationError):
        ProcessEvent(
            event_id="fake",
            kind="stage.approved",
            stage=1,
            iteration=1,
            actor="architect",
            origin="internal",
        )
    process.store.put("owner:case", "owner", {"manager_id": "someone-else"})
    with pytest.raises(ValueError, match="otro responsable"):
        process.get("case")


def test_local_worker_exclusion_is_released_when_the_worker_exits(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'business.sqlite3'}"
    first, second = LocalWorkerLock(database_url), LocalWorkerLock(database_url)
    with first.hold():
        with first.hold():  # serve() owns the lock while run_once() uses it.
            with pytest.raises(Busy, match="worker local"):
                with second.hold():
                    pytest.fail("A second worker acquired the same database")
    with second.hold():
        pass
