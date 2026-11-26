"""Read existing local records for a report. No providers, inference or engineering."""

from hashlib import sha256

from app.delivery.engineering_models import (
    EngineeringEvidence,
    EngineeringIntake,
    digest,
)
from app.delivery.metrics import case_metrics
from app.delivery.models import EngineeringHandoff


class CaseReportSources:
    def __init__(self, workflow_store, delivery_repository, engineering=None):
        self.store, self.deliveries = workflow_store, delivery_repository
        self.engineering = engineering

    def capture(self, request, operator):
        if request.intake_id:
            # The importer and process use this same lock order. Freeze receipts
            # and measured intervals together without starting any worker.
            with (
                self.store.lock(f"engineering:{request.intake_id}"),
                self.store.lock(f"process:{request.case_id}"),
            ):
                return self._capture(request, operator)
        return self._capture(request, operator)

    def _capture(self, request, operator):
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
        engineering = None
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
        if request.intake_id:
            engineering = self._engineering(request, operator, project)
            blockers.extend(engineering["blockers"])
            sources.append(
                {
                    "reference": f"workflow:engineering:{request.intake_id}",
                    "provenance": "operator_recorded",
                    "sha256": engineering["intake"]["input_sha256"],
                }
            )
            for run in engineering["evidence"]:
                sources.append(
                    {
                        "reference": run["evidence"]["run_reference"],
                        "provenance": "operator_recorded",
                        "sha256": run["evidence_sha256"],
                        "run_id": run["run_id"],
                    }
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
        if engineering:
            engineering["phase_metrics"] = next(
                p for p in metrics["phases"] if p["phase"] == "engineering"
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
            "engineering": engineering,
            "metrics": metrics,
            "measurements": recorded,
            "decisions": decisions,
            "sources": sources,
            "closure_blockers": list(dict.fromkeys(blockers)),
        }

    def _engineering(self, request, operator, project):
        if self.engineering is None:
            raise ValueError(
                "El lector de recepciones de ingeniería no está configurado"
            )
        bundle = self.engineering.get(request.intake_id)
        intake = bundle["intake"]
        if (
            intake["case_id"] != request.case_id
            or intake["project_id"] != project["project_id"]
            or intake["operator"] != operator
        ):
            raise ValueError(
                "La recepción de ingeniería pertenece a otro expediente o responsable"
            )
        model = EngineeringIntake.model_validate(intake["input"])
        if (
            str(model.intake_id) != str(request.intake_id)
            or str(model.intake_id) != intake["intake_id"]
            or model.case_id != request.case_id
            or digest(model.model_dump(mode="json")) != intake["input_sha256"]
        ):
            raise ValueError(
                "El manifiesto de entrada de ingeniería no coincide con su hash"
            )
        files = [*model.architecture.files, *model.finops.files]
        if intake["files"] != [f.model_dump(mode="json") for f in files]:
            raise ValueError(
                "Los archivos de la recepción no coinciden con el manifiesto"
            )
        for run in bundle["evidence"]:
            evidence = EngineeringEvidence.model_validate(run["evidence"])
            if (
                str(evidence.intake_id) != str(request.intake_id)
                or run["intake_id"] != str(request.intake_id)
                or str(evidence.run_id) != run["run_id"]
                or evidence.input_sha256 != intake["input_sha256"]
                or run["input_sha256"] != intake["input_sha256"]
                or digest(evidence.model_dump(mode="json")) != run["evidence_sha256"]
            ):
                raise ValueError(
                    "La corrida no corresponde al manifiesto o hash de ingeniería"
                )
            if run["files"] != [f.model_dump(mode="json") for f in evidence.files]:
                raise ValueError(
                    "Los archivos de la corrida no coinciden con su manifiesto"
                )
            expected_status = (
                "passed"
                if all(c.status == "passed" for c in evidence.checks)
                else (
                    "failed"
                    if any(c.status == "failed" for c in evidence.checks)
                    else "incomplete"
                )
            )
            if run["reported_status"] != expected_status:
                raise ValueError(
                    "El estado de la corrida no coincide con sus comprobaciones"
                )
            files.extend(evidence.files)
        unique = {}
        for file in files:
            # Download from SQL, never from the caller's filesystem or the network.
            self.engineering.read_file(request.intake_id, file.sha256)
            unique[(file.path, file.sha256)] = {
                **file.model_dump(mode="json"),
                "uri": f"delivery://engineering/{request.report_id}/{file.sha256}",
            }
        bundle["files"] = list(unique.values())
        bundle["selected_run_id"] = (
            bundle["evidence"][-1]["run_id"] if bundle["evidence"] else None
        )
        status = {
            "not_received": "sin corridas técnicas",
            "passed": "con comprobaciones informadas como correctas",
            "failed": "con fallos informados",
            "incomplete": "con comprobaciones pendientes",
        }[bundle["evidence_status"]]
        count = len(bundle["evidence"])
        history = (
            "Se conserva una corrida importada."
            if count == 1
            else (
                f"Se conservan {count} corridas importadas."
                if count
                else "Las comprobaciones permanecen pendientes."
            )
        )
        bundle["summary"] = (
            f"Recepción de ingeniería registrada {status}. {history} Revisión técnica e integración pendientes. Los resultados se conservan como declarados por el operador."
        )
        return bundle
