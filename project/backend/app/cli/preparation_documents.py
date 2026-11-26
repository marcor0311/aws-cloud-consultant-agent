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
from app.preparation.deliveries import SCRIPT_NAME
from app.preparation.insumos import MeetingInsumos, MeetingTranscript
from app.preparation.local_intake import start_local_preparation
from app.project_opening.models import OpeningRequest

ROOT = PROJECT_DIR.parent
FIXTURE = PROJECT_DIR / "backend/fixtures/nike-lindora-stuart"
OUTPUT = ROOT / "insumos temporales de agente 1"


def reconcile_approved_preparation(
    database_url, request, *, source=OUTPUT, fixture=FIXTURE
):
    # A five-file fixture describes the presentation inputs, not a new opening.
    request = OpeningRequest.model_validate(request, context={"stored_legacy": True})
    OpeningDocuments(
        source, PROJECT_DIR / "agents/2. meeting assistant/templates/architecture.md"
    ).validate([file for file in request.files if file.name != SCRIPT_NAME])
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
        if (
            state["status"] == "awaiting_review"
            and state.get("review_subject", "presentation") == "presentation"
        ):
            runtime.deliveries.stage(
                request.case_id,
                state["revision"],
                [
                    file.model_dump()
                    for file in request.files
                    if file.name != SCRIPT_NAME
                ],
                source_directory=str(Path(source).resolve()),
            )
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
        elif state["status"] not in {"awaiting_review", "ready_for_stage_2"}:
            raise ValueError("La revisión no se puede conciliar en su estado actual.")
        state = runtime.service.get(request.case_id)["state"]
        exported = None
        if state["status"] == "ready_for_stage_2" and state.get(
            "presentation_approval"
        ):
            exported = OpeningDocuments(
                source,
                PROJECT_DIR / "agents/2. meeting assistant/templates/architecture.md",
                runtime.store,
            ).export_preparation(request.case_id, state["revision"])
        return {
            "case_id": request.case_id,
            "revision": state["revision"],
            "status": state["status"],
            "review_subject": state.get("review_subject"),
            "files": exported["files"] if exported else None,
            "directory": exported["directory"] if exported else None,
            "handoffs": runtime.store.case_handoffs(request.case_id),
            "real_inference_calls": 0,
        }
    finally:
        runtime.close()


def main(argv=None):
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["generate", "reconcile", "export"])
    parser.add_argument("--request", type=Path, default=FIXTURE / "opening.json")
    parser.add_argument("--confirm-prior-approval", action="store_true")
    args = parser.parse_args(argv)
    request = OpeningRequest.model_validate_json(
        args.request.read_text(), context={"stored_legacy": True}
    )
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
        if args.command == "export" or state["status"] == "ready_for_stage_2":
            exported = OpeningDocuments(
                OUTPUT,
                PROJECT_DIR / "agents/2. meeting assistant/templates/architecture.md",
                runtime.store,
            ).export_preparation(request.case_id, state["revision"])
            print(json.dumps(exported, ensure_ascii=False, indent=2))
            return
        expected = content.executive_package(transcript).model_dump()
        if {**state["package"], "speaker_notes": ""} != expected:
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
                runtime.store,
            ).validate(
                [ApprovedFile.model_validate(f) for f in manifest["files"]],
                request.case_id,
            )
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
        source_revision = state.get("presentation_approval", {}).get(
            "revision", state["revision"]
        )
        staged = runtime.store.get(
            f"presentation-files:{request.case_id}:{source_revision}"
        )
        if staged:
            from app.project_opening.models import ApprovedFile

            OpeningDocuments(
                OUTPUT,
                PROJECT_DIR / "agents/2. meeting assistant/templates/architecture.md",
            ).validate([ApprovedFile.model_validate(file) for file in staged["files"]])
            print(
                json.dumps(
                    {
                        "case_id": request.case_id,
                        "status": state["status"],
                        "already_exported": True,
                        "files": staged["files"],
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
            if f.name != SCRIPT_NAME
        ]
        runtime.deliveries.stage(
            request.case_id,
            state["revision"],
            files,
            source_directory=str(OUTPUT.resolve()),
        )
        print(
            json.dumps(
                {
                    "case_id": request.case_id,
                    "status": state["status"],
                    "persistence": "PostgreSQL",
                    "real_inference_calls": 0,
                    "files": files,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
