"""Actual PostgreSQL persistence and LangGraph recovery in an isolated test DB."""

import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

from app.bootstrap import create_document_preparation_runtime, create_opening_runtime
from app.cli.preparation_documents import reconcile_approved_preparation
from app.integrations.opening_documents import OpeningDocuments
from app.integrations.opening_preview import simulate_board_approval
from app.preparation.insumos import MeetingInsumos, MeetingTranscript

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.getenv("WORKFLOW_TEST_POSTGRES_URL"),
    reason="isolated PostgreSQL URL not configured",
)
def test_postgres_queue_checkpoints_and_handoff_survive_restart(tmp_path):
    request = json.loads(
        (ROOT / "project/backend/fixtures/nike-lindora-stuart/opening.json").read_text()
    )
    request["case_id"] = "pg-" + uuid.uuid4().hex
    request["company"] = "Test " + uuid.uuid4().hex[:8]
    source = tmp_path / "inputs"
    source.mkdir()
    for file in request["files"]:
        shutil.copy2(
            ROOT / "insumos temporales de agente 1" / file["name"],
            source / file["name"],
        )
    template = ROOT / "project/agents/2. meeting assistant/templates/architecture.md"
    calls = []

    class GitHub:
        def ensure_repository(self, record):
            return {"url": "https://github.com/test/repo", "default_branch": "main"}

        def publish(self, record, files):
            return {
                "sha": "b" * 40,
                "url": "https://github.com/test/repo/commit/" + "b" * 40,
            }

        def merge_initial_structure(self, record):
            return {"number": 1, "merged": True, "merge_sha": record["commit"]["sha"]}

        def assign_architecture(self, record, body, template):
            if not calls:
                calls.append(record["case_id"])
            return {"number": 1, "url": "https://github.com/test/repo/issues/1"}

    github = GitHub()
    url = os.environ["WORKFLOW_TEST_POSTGRES_URL"]
    reconciled = reconcile_approved_preparation(url, request, source=source)
    fixture = ROOT / "project/backend/fixtures/nike-lindora-stuart"
    preparation = create_document_preparation_runtime(
        url,
        MeetingTranscript.model_validate_json(
            (fixture / "transcript.json").read_text()
        ),
        MeetingInsumos.model_validate_json((fixture / "content.json").read_text()),
        manager_id=request["approved_by"],
    )
    try:
        assert reconciled["review_subject"] == "speaker_notes"
        preparation.service.begin_review(request["case_id"], reconciled["revision"])
        preparation.service.review(
            request["case_id"],
            reconciled["revision"],
            "approve",
            "Guion aprobado en prueba.",
        )
        exported = OpeningDocuments(
            source, template, preparation.store
        ).export_preparation(request["case_id"], reconciled["revision"])
        request["files"] = exported["files"]
    finally:
        preparation.close()
    first = create_opening_runtime(
        url, source, template, github=github, simulated_board_case=request["case_id"]
    )
    try:
        first.service.register(request)
        simulate_board_approval(first.board, request["case_id"])
        assert first.service.run(request["case_id"])["status"] == "delivered"
    finally:
        first.close()
    second = create_opening_runtime(
        url, source, template, github=github, simulated_board_case=request["case_id"]
    )
    try:
        assert second.store.engine.dialect.name == "postgresql"
        assert second.service.get(request["case_id"])["status"] == "delivered"
        assert second.service.run(request["case_id"])["status"] == "delivered"
        assert len(calls) == 1
        handoffs = second.store.case_handoffs(request["case_id"])
        assert len(handoffs) == 10
        assert sum(h["accepted_at"] is not None for h in handoffs) == 9
        assert (
            next(
                r for r in second.service.queue() if r["case_id"] == request["case_id"]
            )["queue_position"]
            == 1
        )
    finally:
        second.close()
