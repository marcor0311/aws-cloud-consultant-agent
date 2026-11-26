"""Full offline acceptance journey; enable with make test-demo after both envs exist."""

import json
import os
import sqlite3
from datetime import datetime

import pytest

from app.demos.workflow import run_demo


@pytest.mark.skipif(os.getenv("RUN_MOCK_E2E") != "1", reason="run with make test-demo")
def test_livekit_booking_to_langgraph_collaboration_and_handoff(tmp_path):
    directory = tmp_path / "full-journey"
    report = run_demo(directory, collaborate=True)
    assert report["external_connections"] == []
    first, second = report["projects"]
    assert first["status"] == "ready_for_stage_2" and first["revision"] == 3
    assert second["status"] == "awaiting_review" and second["revision"] == 1
    assert len(report["slack_outbox"]) == 3
    for project in report["projects"]:
        call = json.loads(
            (directory / f"{project['project_id']}-call.json").read_text()
        )
        assert call["sdk"] == "livekit" and call["call_closed"] is True
        tools = [name for turn in call["trace"] for name in turn["tools"]]
        assert tools == [
            "preparar_confirmacion_cliente",
            "iniciar_verificacion_cliente",
            "validar_codigo_correo",
            "consultar_horarios",
            "agendar_reunion",
            "end_call",
        ]
        folder = (
            directory / "artifacts" / project["project_id"] / f"v{project['revision']}"
        )
        expected = {
            "meeting-transcript.md",
            "executive-summary.md",
            "presentation.md",
        }
        if project["status"] == "ready_for_stage_2":
            expected.add("speaker-notes.md")
        assert {p.name for p in folder.iterdir()} == expected
    metrics = report["metrics"][0]
    assert metrics["stage_1"]["completed_at"] is not None
    assert (
        metrics["stage_1"]["process_union_seconds"] < metrics["stage_1"]["lead_seconds"]
    )
    transfer = next(h for h in metrics["handoffs"] if h["to_phase"] == "stage-2")
    assert transfer["accepted_by"] == "executive-direction-agent"
    with sqlite3.connect(directory / "workflow.sqlite3") as db:
        receipts = [
            json.loads(row[0])
            for row in db.execute(
                "SELECT payload FROM workflow_records WHERE kind='call_receipt'"
            )
        ]
        assert len(receipts) == 2
        for project in report["projects"]:
            call = json.loads(
                (directory / f"{project['project_id']}-call.json").read_text()
            )
            receipt = next(r for r in receipts if r["case_id"] == project["case_id"])
            assert (
                datetime.fromisoformat(receipt["closed_at"]).timestamp()
                >= call["trace"][-1]["ended_at"]
            )
        assert db.execute("SELECT count(*) FROM workflow_projects").fetchone()[0] == 2
        assert (
            db.execute("SELECT count(*) FROM workflow_collaboration_notes").fetchone()[
                0
            ]
            == 2
        )
        assert (
            db.execute(
                "SELECT count(*) FROM workflow_handoffs WHERE accepted_at IS NOT NULL"
            ).fetchone()[0]
            >= 6
        )
