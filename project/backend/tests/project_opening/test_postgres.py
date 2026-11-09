"""Actual PostgreSQL persistence and LangGraph recovery in an isolated test DB."""

import json
import os
import uuid
from pathlib import Path

import pytest

from app.bootstrap import create_opening_runtime
from app.cli.preparation_documents import reconcile_approved_preparation
from app.integrations.opening_preview import simulate_board_approval

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
    source = ROOT / "insumos temporales de agente 1"
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
    reconcile_approved_preparation(url, request)
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
        assert len(handoffs) == 9
        assert sum(h["accepted_at"] is not None for h in handoffs) == 8
        assert (
            next(
                r for r in second.service.queue() if r["case_id"] == request["case_id"]
            )["queue_position"]
            == 1
        )
    finally:
        second.close()
