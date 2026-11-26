"""FinOps correction cycle reopens Architecture without rewriting history."""

import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import ValidationError

from app.architecture.catalog import BaselineCatalog
from app.architecture.corrections import FinOpsCorrectionRequest
from app.architecture.demo import DEFAULT_INPUT
from app.architecture.graph import build_graph
from app.architecture.service import ArchitectureService
from app.integrations.langgraph import LangGraphExecution
from app.persistence.workflow import WorkflowStore
from app.workflow.graph import build_process_graph
from app.workflow.service import ProcessService

BASELINES = (
    Path(__file__).resolve().parents[5] / "aws-cloud-consultant-baseline-modules"
)


def service_at(root):
    connection = sqlite3.connect(root / "checkpoints.sqlite3", check_same_thread=False)
    store = WorkflowStore(f"sqlite:///{root / 'workflow.sqlite3'}")
    catalog = BaselineCatalog(BASELINES)
    service = ArchitectureService(
        LangGraphExecution(build_graph(SqliteSaver(connection), catalog)),
        catalog,
        store,
    )
    return connection, store, service


def package():
    return json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))


def correction(revision=1, request_id="finops-correction-001"):
    return {
        "contract_version": "1.0",
        "request_id": request_id,
        "architecture_id": "case-19",
        "project_id": "documentos-demo",
        "source_revision": revision,
        "reason": "La transferencia estimada supera el límite presupuestario.",
        "affected_resources": ["documents"],
        "affected_dimensions": [
            {"resource_id": "documents", "dimension_id": "internet-transfer"}
        ],
        "requested_changes": [
            "Reducir y justificar la transferencia mensual hacia Internet."
        ],
        "new_constraints": ["Transferencia máxima objetivo de 5 GB por mes."],
        "finops_evaluation_reference": "finops://case-19/evaluations/1",
        "requested_at": "2026-11-08T15:00:00-06:00",
        "requested_by": "finops-agent",
        "origin": "finops",
    }


def approve_revision_one(service):
    started = service.start("case-19", "issue-19-v1", package())["state"]
    return service.review("case-19", 1, started["artifact_sha256"], "approve")["state"]


def close(connection, store):
    store.engine.dispose()
    connection.close()


def test_correction_rejects_missing_architecture_and_wrong_revision(tmp_path):
    connection, store, service = service_at(tmp_path)
    with pytest.raises(ValueError, match="no tiene un diseño"):
        service.request_finops_correction("case-19", correction())

    approve_revision_one(service)
    stale = correction(revision=2)
    with pytest.raises(ValueError, match="revisión entregada"):
        service.request_finops_correction("case-19", stale)
    close(connection, store)


def test_correction_validates_affected_resources_and_dimensions(tmp_path):
    connection, store, service = service_at(tmp_path)
    approve_revision_one(service)
    unknown_resource = correction()
    unknown_resource["affected_resources"] = ["unknown"]
    with pytest.raises(ValueError, match="recursos desconocidos"):
        service.request_finops_correction("case-19", unknown_resource)

    unknown_dimension = correction()
    unknown_dimension["affected_dimensions"][0]["dimension_id"] = "unknown"
    with pytest.raises(ValueError, match="dimensiones desconocidas"):
        service.request_finops_correction("case-19", unknown_dimension)
    close(connection, store)


def test_correction_requires_a_traceable_finops_evaluation():
    invalid = correction()
    invalid["finops_evaluation_reference"] = "free form reference"
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        FinOpsCorrectionRequest.model_validate(invalid)


def test_duplicate_correction_is_idempotent_and_conflict_is_rejected(tmp_path):
    connection, store, service = service_at(tmp_path)
    approve_revision_one(service)
    request = correction()

    first = service.request_finops_correction("case-19", request)
    duplicate = service.request_finops_correction("case-19", request)

    assert first["duplicate"] is False
    assert duplicate["duplicate"] is True
    assert len(service.history("case-19")["corrections"]) == 1
    conflicting = deepcopy(request)
    conflicting["reason"] = "Contenido diferente con el mismo identificador."
    with pytest.raises(ValueError, match="otro contenido"):
        service.request_finops_correction("case-19", conflicting)
    close(connection, store)


def test_complete_finops_rework_cycle_preserves_history_and_handoffs(tmp_path):
    connection, store, service = service_at(tmp_path)
    revision_one = approve_revision_one(service)
    first_hash = revision_one["artifact_sha256"]
    first_handoff = deepcopy(revision_one["handoff"])
    first_artifact = deepcopy(store.get("architecture-artifact:case-19:1"))

    reopened = service.request_finops_correction("case-19", correction())
    assert reopened["state"]["status"] == "finops_changes_requested"
    assert reopened["state"]["revision"] == 1
    phase = store.get("phase:case-19:stage-3")
    assert phase["completed_at"] is None

    corrected = package()
    transfer = corrected["economic_contract"]["pricing_inputs"][0]["dimensions"][2]
    transfer["quantity"] = "5"
    transfer["source"]["notes"] = (
        "Restricción incorporada desde la evaluación FinOps 1."
    )
    revision_two = service.revise_from_finops(
        "case-19", "finops-correction-001", corrected
    )["state"]

    retry = service.revise_from_finops("case-19", "finops-correction-001", corrected)
    assert retry["duplicate"] is True
    assert retry["state"]["revision"] == 2

    assert revision_two["revision"] == 2
    assert revision_two["parent_revision"] == 1
    assert revision_two["correction_request_id"] == "finops-correction-001"
    assert revision_two["status"] == "awaiting_review"
    assert revision_two["handoff"] == {}
    assert revision_two["artifact_sha256"] != first_hash
    with pytest.raises(ValueError, match="revisión pendiente exacta"):
        service.review("case-19", 1, first_hash, "approve")

    final = service.review("case-19", 2, revision_two["artifact_sha256"], "approve")[
        "state"
    ]
    assert final["status"] == "ready_for_finops"
    assert final["handoff"]["revision"] == 2
    assert final["handoff"] != first_handoff

    history = service.history("case-19")
    assert [item["revision"] for item in history["revisions"]] == [1, 2]
    assert [item["revision"] for item in history["approvals"]] == [1, 2]
    assert [item["revision"] for item in history["handoffs"]] == [1, 2]
    assert len(history["corrections"]) == 1
    assert store.get("architecture-artifact:case-19:1") == first_artifact
    assert store.get("architecture-artifact:case-19:2") is not None

    service._sync("case-19")
    service._sync("case-19")
    handoffs = [
        item
        for item in store.case_handoffs("case-19")
        if item["to_actor"] == "finops-agent"
    ]
    assert [item["revision"] for item in handoffs] == [1, 2]
    assert len(store.list("architecture_handoff")) == 2
    assert service.metrics("case-19")["rework_cycles"] == 1
    close(connection, store)


def test_finops_revision_must_change_architecture(tmp_path):
    connection, store, service = service_at(tmp_path)
    approve_revision_one(service)
    service.request_finops_correction("case-19", correction())

    with pytest.raises(ValueError, match="debe modificar"):
        service.revise_from_finops("case-19", "finops-correction-001", package())

    close(connection, store)


def test_history_survives_restart(tmp_path):
    connection, store, service = service_at(tmp_path)
    approve_revision_one(service)
    service.request_finops_correction("case-19", correction())
    corrected = package()
    corrected["open_questions"] = ["Validar el nuevo límite de transferencia."]
    pending = service.revise_from_finops("case-19", "finops-correction-001", corrected)[
        "state"
    ]
    service.review("case-19", 2, pending["artifact_sha256"], "approve")
    close(connection, store)

    connection, store, restarted = service_at(tmp_path)
    history = restarted.history("case-19")
    assert history["current_revision"] == 2
    assert len(history["revisions"]) == 2
    assert len(history["corrections"]) == 1
    assert len(history["handoffs"]) == 2
    close(connection, store)


def test_specialized_rework_stays_coherent_with_main_process(tmp_path):
    connection = sqlite3.connect(
        tmp_path / "combined-checkpoints.sqlite3", check_same_thread=False
    )
    saver = SqliteSaver(connection)
    store = WorkflowStore(f"sqlite:///{tmp_path / 'combined-workflow.sqlite3'}")
    store.put("owner:case-19", "owner", {"case_id": "case-19", "manager_id": "manager"})
    process = ProcessService(
        LangGraphExecution(build_process_graph(saver)), store, "manager"
    )
    process.ensure("case-19")
    preparation = {
        "revision": 1,
        "artifact_sha256": "a" * 64,
        "evidence": ["artifact:case-19:1"],
    }
    process.internal("case-19", "transcript:1", "transcript.available")
    process.internal("case-19", "preparation:1", "preparation.ready", **preparation)
    process.internal(
        "case-19", "preparation-approved:1", "preparation.approved", **preparation
    )
    process.internal("case-19", "direction-approved:1", "stage.approved", **preparation)

    catalog = BaselineCatalog(BASELINES)
    architecture = ArchitectureService(
        LangGraphExecution(build_graph(saver, catalog)),
        catalog,
        store,
        process,
        "cloud-solutions-architect",
    )
    first = architecture.start("case-19", "issue-19-v1", package())["state"]
    architecture.review("case-19", 1, first["artifact_sha256"], "approve")
    assert process.get("case-19")["state"]["stage"] == 4

    finops = {
        "revision": 1,
        "artifact_sha256": "b" * 64,
        "evidence": ["finops-evaluation:case-19:1"],
    }
    process.internal("case-19", "finops-ready:1", "deliverable.ready", **finops)
    process.internal(
        "case-19",
        "finops-return:1",
        "stage.changes_requested",
        revision=1,
        artifact_sha256="b" * 64,
        comment="El costo requiere un ajuste de transferencia.",
    )
    assert process.get("case-19")["state"]["stage"] == 3

    architecture.request_finops_correction("case-19", correction())
    corrected = package()
    corrected["economic_contract"]["pricing_inputs"][0]["dimensions"][2]["quantity"] = (
        "5"
    )
    second = architecture.revise_from_finops(
        "case-19", "finops-correction-001", corrected
    )["state"]
    architecture.review("case-19", 2, second["artifact_sha256"], "approve")

    process_state = process.get("case-19")["state"]
    assert process_state["stage"] == 4
    assert process_state["status"] == "awaiting_deliverable"
    assert process_state["rework_cycles"] == 1
    assert len(architecture.history("case-19")["handoffs"]) == 2
    close(connection, store)
