"""Optional real PostgreSQL check; run against an isolated, disposable test database."""

import os
import uuid

import pytest

from app.bootstrap import create_runtime
from app.preparation.models import ExecutivePackage
from app.workflow.settings import WorkflowSettings


@pytest.mark.skipif(
    not os.getenv("WORKFLOW_TEST_POSTGRES_URL"),
    reason="isolated PostgreSQL URL not configured",
)
def test_postgres_persists_checkpoints_artifacts_and_timing_across_process_restart():
    url = os.environ["WORKFLOW_TEST_POSTGRES_URL"]
    settings = WorkflowSettings(
        database_url=url.replace("postgresql://", "postgresql+psycopg://", 1),
        checkpoint_url=url,
        manager_id="fixture-manager",
    )
    case_id = f"postgres-{uuid.uuid4().hex}"
    unknown = {"text": "No confirmado", "status": "unknown", "citations": []}
    package = ExecutivePackage(
        summary="Borrador de prueba",
        needs=[],
        requirements=[],
        budget=unknown,
        timeline=unknown,
        risks=[],
        open_questions=["Confirmar presupuesto"],
        related_projects=[],
        presentation=[],
        speaker_notes="Guion de prueba",
    )
    runtime = create_runtime(settings, drafter=lambda _: package)
    try:
        first = runtime.service.start(
            case_id, "manual-fixture", "Reunión ficticia.", "merchandising"
        )
        assert first["state"]["status"] == "awaiting_review"
        assert len(runtime.store.list("reference")) == 48
    finally:
        runtime.close()
    restarted = create_runtime(settings, drafter=lambda _: package)
    try:
        assert restarted.service.get(case_id)["state"]["revision"] == 1
        final = restarted.service.review(case_id, 1, "approve")
        assert final["state"]["status"] == "ready_for_stage_2"
        assert (
            restarted.store.get(f"handoff:{case_id}")["manager_id"] == "fixture-manager"
        )
        assert (
            restarted.service.metrics(case_id)["phases"][0]["completed_at"] is not None
        )
    finally:
        restarted.close()
