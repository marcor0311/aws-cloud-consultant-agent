"""Durable document preparation and explicit reconciliation of previously approved files."""

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from app.bootstrap import create_document_preparation_runtime
from app.core.config import PROJECT_DIR, load_environment
from app.integrations.insumos_export import FILENAMES, export_insumos
from app.integrations.opening_documents import OpeningDocuments
from app.preparation.insumos import MeetingInsumos, MeetingTranscript
from app.preparation.local_intake import start_local_preparation
from app.project_opening.models import OpeningRequest

ROOT = PROJECT_DIR.parent
FIXTURE = PROJECT_DIR / "backend/fixtures/nike-lindora-stuart"
OUTPUT = ROOT / "insumos temporales de agente 1"


def reconcile_approved_preparation(
    database_url, request, *, source=OUTPUT, fixture=FIXTURE
):
    request = OpeningRequest.model_validate(request)
    OpeningDocuments(
        source, PROJECT_DIR / "agents/2. meeting assistant/templates/architecture.md"
    ).validate(request.files)
    transcript = MeetingTranscript.model_validate_json(
        (fixture / "transcript.json").read_text()
    )
    content = MeetingInsumos.model_validate_json((fixture / "content.json").read_text())
    runtime = create_document_preparation_runtime(
        database_url, transcript, content, manager_id=request.approved_by
    )
    try:
        result = start_local_preparation(
            runtime,
            request.case_id,
            transcript,
            provenance="reconciled_local_documents",
        )
        state = result["state"]
        runtime.deliveries.bind(
            request.case_id,
            state["revision"],
            [f.model_dump() for f in request.files],
            approval_reference=request.approval_reference,
            provenance="reconciled_local_documents",
        )
        runtime.store.event(
            f"reconciliation:{request.case_id}:{state['revision']}",
            request.case_id,
            "preparation.reconciled",
            {
                "approval_reference": request.approval_reference,
                "recorded_at": runtime.store.clock(),
                "historical_occurred_at": None,
                "calendar_call_recorded": False,
                "real_inference_calls": 0,
            },
        )
        if state["status"] == "awaiting_review":
            runtime.store.accept_handoff(
                f"{request.case_id}:preparation:stuart:v{state['revision']}",
                request.approved_by,
            )
            runtime.service.review(
                request.case_id,
                state["revision"],
                "approve",
                request.approval_reference,
            )
        elif state["status"] != "ready_for_stage_2":
            raise ValueError("La revisión no se puede conciliar en su estado actual.")
        return {
            "case_id": request.case_id,
            "revision": state["revision"],
            "handoffs": runtime.store.case_handoffs(request.case_id),
            "real_inference_calls": 0,
        }
    finally:
        runtime.close()


def main(argv=None):
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["generate", "reconcile"])
    parser.add_argument("--request", type=Path, default=FIXTURE / "opening.json")
    parser.add_argument("--confirm-prior-approval", action="store_true")
    args = parser.parse_args(argv)
    request = OpeningRequest.model_validate_json(args.request.read_text())
    database_url = os.getenv("WORKFLOW_DATABASE_URL", "")
    if args.command == "reconcile":
        if not args.confirm_prior_approval:
            parser.error(
                "Conciliar requiere --confirm-prior-approval y una aprobación previa expresa."
            )
        print(
            json.dumps(
                reconcile_approved_preparation(
                    database_url, request.model_dump(mode="json")
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    transcript = MeetingTranscript.model_validate_json(
        (FIXTURE / "transcript.json").read_text()
    )
    content = MeetingInsumos.model_validate_json((FIXTURE / "content.json").read_text())
    runtime = create_document_preparation_runtime(
        database_url, transcript, content, manager_id=request.approved_by
    )
    try:
        result = start_local_preparation(
            runtime, request.case_id, transcript, provenance="local_document_generation"
        )
        state = result["state"]
        if state["package"] != content.executive_package(transcript).model_dump():
            raise ValueError(
                "El contenido preparado cambió; debe crearse una nueva revisión."
            )
        manifest = runtime.store.get(
            f"artifact-files:{request.case_id}:{state['revision']}"
        )
        if manifest:
            from app.project_opening.models import ApprovedFile

            OpeningDocuments(
                OUTPUT,
                PROJECT_DIR / "agents/2. meeting assistant/templates/architecture.md",
            ).validate([ApprovedFile.model_validate(f) for f in manifest["files"]])
            print(
                json.dumps(
                    {
                        "case_id": request.case_id,
                        "status": state["status"],
                        "already_exported": True,
                        "real_inference_calls": 0,
                    },
                    ensure_ascii=False,
                )
            )
            return
        with tempfile.TemporaryDirectory(prefix="stuart-insumos-") as temporary:
            staging = Path(temporary)
            export_insumos(transcript, content, staging, status=state["status"])
            OUTPUT.mkdir(exist_ok=True)
            for name in FILENAMES:
                shutil.copy2(staging / name, OUTPUT / name)
            shutil.copy2(
                FIXTURE / "transcript.md", OUTPUT / "transcripcion-reunion-nike.md"
            )
        files = [
            {
                "name": f.name,
                "sha256": hashlib.sha256((OUTPUT / f.name).read_bytes()).hexdigest(),
            }
            for f in request.files
        ]
        runtime.deliveries.bind(request.case_id, state["revision"], files)
        print(
            json.dumps(
                {
                    "case_id": request.case_id,
                    "status": state["status"],
                    "persistence": "PostgreSQL",
                    "real_inference_calls": 0,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
