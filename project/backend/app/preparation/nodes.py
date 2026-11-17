"""Preparation steps; model access is injected and human review is explicit."""

import hashlib
import json
from contextlib import nullcontext
from datetime import datetime, timezone

from langgraph.types import interrupt

from app.preparation.deliveries import PreparationDeliveries, files_digest
from app.preparation.models import MEETING_EVIDENCE_INSTRUCTIONS, ExecutivePackage
from app.preparation.ports import DraftGenerator
from app.preparation.processing import (
    CORPORATE_CONTRACT,
    DOCUMENT_CONTRACTS,
    PROCESSOR_INSTRUCTIONS,
)
from app.preparation.speaker_notes import compose_speaker_notes, presentation_digest
from app.preparation.state import meeting_documents, meeting_sources, utc_now


class PreparationNodes:
    def __init__(
        self, drafter: DraftGenerator | None = None, store=None, package_model=None
    ):
        self.drafter = drafter
        self.store = store
        self.package_model = package_model or ExecutivePackage

    def wait_for_meeting(self, state):
        event = interrupt(
            {
                "action": "await_meeting_transcript",
                "case_id": state["case_id"],
                "message": "Reunión confirmada; esperar a que termine la reunión humana y llegue la transcripción.",
            }
        )
        if event.get("cancelled"):
            return {"status": "meeting_cancelled"}
        if not event.get("transcript", "").strip():
            raise ValueError("La preparación requiere la transcripción de la reunión.")
        return {**event, "status": "awaiting_draft"}

    def prepare_input(self, state):
        return {"status": "awaiting_draft"}

    def draft(self, state):
        if self.drafter is not None:
            revision = state.get("revision", 0) + 1
            key = f"artifact:{state['case_id']}:{revision}"
            artifact = self.store.get(key) if self.store else None
            if artifact is None:
                with (
                    self.store.work(state["case_id"], "preparation")
                    if self.store
                    else nullcontext()
                ):
                    package = self.drafter(state)
                    if self.package_model is ExecutivePackage:
                        package = package.model_copy(update={"speaker_notes": ""})
                artifact = {
                    "case_id": state["case_id"],
                    "revision": revision,
                    "package": package.model_dump(),
                    "documents": {
                        **meeting_documents(state),
                        **package.artifacts(),
                    },
                }
                if self.store:
                    self.store.put(key, "artifact", artifact)
            return {
                "package": artifact["package"],
                "draft": artifact["documents"]["executive-summary.md"],
                "revision": revision,
                "status": "awaiting_review",
                "review_subject": "presentation",
                "presentation_approval": {},
                "deliverable_contract": CORPORATE_CONTRACT
                if self.package_model is not ExecutivePackage
                else "legacy",
            }
        # No external side effects before interrupt: this node restarts on resume.
        text = interrupt(
            {
                "action": "draft_with_chatgpt",
                "instructions": PROCESSOR_INSTRUCTIONS
                if self.package_model is not ExecutivePackage
                else (
                    MEETING_EVIDENCE_INSTRUCTIONS
                    + "Preparar necesidades, requisitos, presupuesto, plazos, riesgos, "
                    "preguntas pendientes, citas de la reunión y propuesta de "
                    "presentación. Marcar lo no mencionado como no confirmado. "
                    "Devolver JSON ExecutivePackage, con speaker_notes vacío: el guion "
                    "solo se genera después de aprobar la presentación. "
                    "Guardar el borrador y pedir revisión al Engagement Manager."
                ),
                "schema": self.package_model.model_json_schema(),
                "transcript": state["transcript"],
                "meeting_notes": state.get("meeting_notes", ""),
                "feedback": state.get("feedback", ""),
            }
        )
        if not isinstance(text, str) or not text.strip():
            raise ValueError("El borrador no puede estar vacío.")
        package = self._validate_package(
            state, self.package_model.model_validate_json(text)
        )
        revision = state.get("revision", 0) + 1
        artifact = self._artifact(state, revision, package)
        return {
            "package": artifact["package"],
            "draft": artifact["documents"]["executive-summary.md"],
            "revision": revision,
            "status": "awaiting_review",
            "review_subject": "presentation",
            "presentation_approval": {},
            "deliverable_contract": CORPORATE_CONTRACT
            if self.package_model is not ExecutivePackage
            else "legacy",
        }

    def _validate_package(self, state, package):
        return (
            package.validate_sources(meeting_sources(state))
            if isinstance(package, ExecutivePackage)
            else package
        )

    def _artifact(self, state, revision, package, **metadata):
        artifact = {
            "case_id": state["case_id"],
            "revision": revision,
            "package": package.model_dump(),
            "documents": {
                **meeting_documents(state),
                **package.artifacts(),
            },
            **metadata,
        }
        if self.store:
            self.store.put(
                f"artifact:{state['case_id']}:{revision}", "artifact", artifact
            )
        return artifact

    def review(self, state):
        response = interrupt(
            {
                "action": "manager_review",
                "draft": state["draft"],
                "revision": state["revision"],
                "subject": state.get("review_subject", "presentation"),
                "package": state.get("package"),
            }
        )
        if not isinstance(response, dict) or response.get("decision") not in {
            "approve",
            "revise",
        }:
            raise ValueError("La decisión debe ser approve o revise.")
        if (
            response["decision"] == "revise"
            and not response.get("feedback", "").strip()
        ):
            raise ValueError("Indicar los ajustes solicitados.")
        result = {
            "decision": response["decision"],
            "feedback": response.get("feedback", ""),
            "status": "approved"
            if response["decision"] == "approve"
            else "awaiting_draft",
        }
        if (
            response["decision"] == "approve"
            and state.get("deliverable_contract") not in DOCUMENT_CONTRACTS
        ):
            if state.get("review_subject", "presentation") == "presentation":
                result["presentation_approval"] = {
                    "revision": state["revision"],
                    "presentation_sha256": presentation_digest(state["package"]),
                    "artifact_sha256": hashlib.sha256(
                        json.dumps(state["package"], sort_keys=True).encode()
                    ).hexdigest(),
                }
                if self.store:
                    files = PreparationDeliveries(self.store).presentation_files(
                        state["case_id"], state["revision"], state["package"]
                    )
                    result["presentation_approval"]["files_sha256"] = files_digest(
                        files
                    )
            elif (
                not state.get("presentation_approval")
                or state["presentation_approval"]["presentation_sha256"]
                != presentation_digest(state["package"])
                or not state["package"]["speaker_notes"].strip()
            ):
                raise ValueError("El guion requiere la presentación aprobada vigente.")
        return result

    def generate_speaker_notes(self, state):
        approval = state["presentation_approval"]
        if approval["presentation_sha256"] != presentation_digest(state["package"]):
            raise ValueError("La presentación cambió después de aprobarse.")
        revision = state["revision"] + 1
        key = f"artifact:{state['case_id']}:{revision}"
        artifact = self.store.get(key) if self.store else None
        if artifact is not None:
            if artifact.get("presentation_approval") != approval:
                raise ValueError("La revisión del guion requiere conciliación.")
        else:
            with (
                self.store.work(state["case_id"], "preparation")
                if self.store
                else nullcontext()
            ):
                package = ExecutivePackage.model_validate(state["package"])
                package = package.model_copy(
                    update={"speaker_notes": compose_speaker_notes(package)}
                )
                artifact = self._artifact(
                    state, revision, package, presentation_approval=approval
                )
        if self.store:
            self.store.event(
                f"speaker-notes:{state['case_id']}:{revision}",
                state["case_id"],
                "preparation.speaker_notes_generated",
                {
                    "revision": revision,
                    "presentation_approval": approval,
                    "inference_calls": 0,
                },
            )
        return {
            "package": artifact["package"],
            "draft": artifact["documents"]["executive-summary.md"],
            "revision": revision,
            "status": "awaiting_review",
            "review_subject": "speaker_notes",
            "decision": "",
        }

    def revise_speaker_notes(self, state):
        text = interrupt(
            {
                "action": "revise_speaker_notes",
                "revision": state["revision"],
                "presentation": state["package"]["presentation"],
                "speaker_notes": state["package"]["speaker_notes"],
                "feedback": state["feedback"],
                "instructions": "Revisar solo el guion desde el chat y guardarlo con guardar_guion_revisado. No cambiar la presentación ni inventar acuerdos.",
            }
        )
        if not isinstance(text, str) or not text.strip():
            raise ValueError("El guion revisado no puede estar vacío.")
        package = ExecutivePackage.model_validate(state["package"]).model_copy(
            update={"speaker_notes": text.strip()}
        )
        revision = state["revision"] + 1
        artifact = self._artifact(
            state,
            revision,
            package,
            presentation_approval=state["presentation_approval"],
        )
        return {
            "package": artifact["package"],
            "revision": revision,
            "status": "awaiting_review",
            "decision": "",
        }

    def handoff(self, state):
        return {
            "handed_off_at": datetime.fromtimestamp(
                self.store.clock(), timezone.utc
            ).isoformat()
            if self.store
            else utc_now(),
            "status": "ready_for_stage_2",
            "handoff": {
                "id": f"{state['case_id']}:stage-1:stage-2",
                "target_stage": 2,
                "revision": state["revision"],
                "draft": state["draft"],
                "delivery": "local_package_only",
                "package": state.get("package"),
            },
        }
