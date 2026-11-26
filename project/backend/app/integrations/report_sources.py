"""Read existing local records for a report. No providers, inference or engineering."""

from hashlib import sha256

from app.delivery.metrics import case_metrics
from app.delivery.models import EngineeringHandoff


class CaseReportSources:
    def __init__(self, workflow_store, delivery_repository):
        self.store, self.deliveries = workflow_store, delivery_repository

    def capture(self, request, operator):
        project = next(
            (
                p
                for p in self.store.project_list(operator)
                if p["case_id"] == request.case_id
            ),
            None,
        )
        if not project:
            raise ValueError("Expediente inexistente o de otro responsable")
        captured = self.store.clock()
        recorded = self.store.metrics(request.case_id)
        opening = self.store.get(f"opening:{request.case_id}") or {}
        sources = [
            {
                "reference": f"workflow:project:{request.case_id}",
                "provenance": "fictitious" if project["is_fictitious"] else "recorded",
            }
        ]
        status = self.store.get(f"status:{request.case_id}") or {}
        manifest = self.store.get(
            f"artifact-files:{request.case_id}:{status.get('revision')}"
        )
        if manifest:
            sources.append(
                {
                    "reference": f"workflow:artifact-files:{request.case_id}:{status['revision']}",
                    "provenance": "recorded",
                    "revision": status["revision"],
                    "sha256": manifest.get("artifact_sha256"),
                    "files": [
                        {k: f[k] for k in ("name", "sha256") if k in f}
                        for f in manifest.get("files", [])
                    ],
                }
            )
        budget = opening.get("budget")
        if budget:
            sources.append(
                {
                    "reference": f"workflow:opening:{request.case_id}",
                    "provenance": "fictitious"
                    if opening.get("is_fictitious")
                    else "recorded",
                    "approval_reference": opening.get("approval_reference"),
                }
            )
        technical = None
        blockers = [
            "Falta la entrega de ingeniería real, integrada y aprobada del issue #21."
        ]
        if request.engineering_delivery_id:
            row = self.deliveries.get(request.engineering_delivery_id)
            if not row or not row["handoff"]:
                raise ValueError("Entrega técnica no encontrada o incompleta")
            handoff = EngineeringHandoff.model_validate(row["handoff"])
            if handoff.project_id != project["project_id"]:
                raise ValueError("La entrega técnica pertenece a otro proyecto")
            for ref in handoff.artifacts:
                artifact = self.deliveries.artifact(
                    request.engineering_delivery_id, ref.artifact_id
                )
                if (
                    not artifact
                    or sha256(bytes(artifact["content"])).hexdigest() != ref.sha256
                ):
                    raise ValueError("La evidencia técnica no coincide con sus hashes")
            technical = handoff.model_dump(mode="json")
            sources.append(
                {
                    "reference": f"delivery:{request.engineering_delivery_id}:{handoff.handoff_id}",
                    "provenance": "simulated_inputs",
                    "review_status": handoff.review_status,
                    "integration_status": handoff.integration_status,
                }
            )
            blockers.append(
                "Arquitectura y FinOps de la entrega adjunta son simulados."
            )
        if project["is_fictitious"]:
            blockers.append("El expediente está identificado como ficticio.")
        decisions = [
            {"id": e["id"], "kind": e["kind"], "at": e["at"], "payload": e["payload"]}
            for e in self.store.case_events(request.case_id)
            if e["kind"]
            in {
                "process.transition",
                "approval.decided",
                "opening.approved",
                "opening.rejected",
            }
        ]
        metrics = case_metrics(recorded, captured)
        # Count authoritative changes requested without also counting GitHub observations.
        metrics["process_rework_cycles"] = sum(
            d["kind"] == "process.transition"
            and d["payload"].get("kind") == "stage.changes_requested"
            for d in decisions
        )
        return {
            "schema_version": "1.0",
            "case_id": request.case_id,
            "project": project,
            "captured_at": captured,
            "process": self.store.get(f"process:{request.case_id}"),
            "budget": budget,
            "budget_period": None,
            "technical": technical,
            "metrics": metrics,
            "measurements": recorded,
            "decisions": decisions,
            "sources": sources,
            "closure_blockers": blockers,
        }
