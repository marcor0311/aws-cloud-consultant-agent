"""Record engineering input and existing evidence; never execute infrastructure."""

import base64
import re
from hashlib import sha256
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from app.delivery.engineering_models import (
    EngineeringEvidence,
    EngineeringIntake,
    EngineeringRelease,
    digest,
)
from app.delivery.metrics import case_metrics
from app.persistence.delivery import DeliveryConflict


class IntakeState(TypedDict):
    recorded: bool


class EngineeringService:
    def __init__(self, repository, files, operator):
        if not operator or not operator.strip():
            raise ValueError("Configurar ENGINEERING_OPERATOR con el responsable local")
        self.repository, self.files, self.operator = repository, files, operator

    def _project(self, case_id):
        project = next(
            (
                p
                for p in self.repository.store.project_list(self.operator)
                if p["case_id"] == case_id
            ),
            None,
        )
        if not project:
            raise ValueError("Expediente inexistente o de otro responsable")
        return project

    def _upstream(self, request, *, delivered=False):
        store = self.repository.store
        if request.finops_architecture_sha256 != request.approval_digest(3):
            raise DeliveryConflict(
                "FinOps no referencia el manifiesto aprobado exacto de arquitectura"
            )
        state = store.get(f"process:{request.case_id}") or {}
        if not (
            state.get("stage") == 5
            and state.get("status") == "awaiting_deliverable"
            or delivered
            and state.get("stage") in (5, 6)
        ):
            raise DeliveryConflict(
                "El proceso no está esperando la entrega de ingeniería"
            )
        events = [
            e["payload"]
            for e in store.case_events(request.case_id)
            if e["kind"] == "process.transition"
        ]
        approvals = []
        for stage, package in ((3, request.architecture), (4, request.finops)):
            approval = next(
                (e for e in events if e.get("event_id") == package.approval.event_id),
                None,
            )
            if (
                not approval
                or (
                    approval.get("kind"),
                    approval.get("from_stage"),
                    approval.get("to_stage"),
                    approval.get("revision"),
                    approval.get("artifact_sha256"),
                    approval.get("actor"),
                )
                != (
                    "stage.approved",
                    stage,
                    stage + 1,
                    package.revision,
                    request.approval_digest(stage),
                    package.approval.actor,
                )
                or package.approval.reference not in approval.get("evidence", [])
            ):
                raise DeliveryConflict(
                    "Falta la decisión registrada sobre la versión y manifiesto exactos de Arquitectura o FinOps"
                )
            approvals.append(approval)
        if (
            approvals[0]["to_iteration"] != approvals[1]["from_iteration"]
            or approvals[1]["to_iteration"]
            != max(
                e["to_iteration"]
                for e in events
                if e.get("kind") == "stage.approved" and e.get("from_stage") == 4
            )
            or approvals[1]["to_iteration"] > state["iteration"]
        ):
            raise DeliveryConflict(
                "Las aprobaciones pertenecen a un ciclo anterior del proceso"
            )
        handoff = store.handoff(request.incoming_handoff_id)
        if (
            not handoff
            or (
                handoff["case_id"],
                handoff["from_phase"],
                handoff["to_phase"],
                handoff["to_actor"],
                handoff["from_actor"],
                handoff["revision"],
                handoff["artifact_sha256"],
            )
            != (
                request.case_id,
                "stage-4",
                "stage-5",
                self.operator,
                request.finops.approval.actor,
                request.finops.revision,
                request.approval_digest(4),
            )
            or handoff["accepted_by"] not in (None, self.operator)
        ):
            raise DeliveryConflict(
                "La entrega de FinOps no corresponde a este responsable o revisión"
            )
        return handoff

    def register(self, request):
        project = self._project(request.case_id)
        key = str(request.intake_id)
        input_sha256 = digest(request.model_dump(mode="json"))
        with (
            self.repository.store.lock(f"engineering:{key}"),
            self.repository.store.lock(f"process:{request.case_id}"),
        ):
            previous = self.repository.get(key)
            if previous:
                if (
                    previous["input_sha256"] != input_sha256
                    or previous["operator"] != self.operator
                ):
                    raise DeliveryConflict("El intake_id ya corresponde a otra entrada")
                return self.get(request.intake_id)

            def validate(_state):
                self._upstream(request)
                return {}

            def record(_state):
                handoff = self._upstream(request)
                files = self.files.read(
                    [*request.architecture.files, *request.finops.files]
                )
                self.repository.register(
                    request, input_sha256, self.operator, files, project, handoff
                )
                return {"recorded": True}

            graph = StateGraph(IntakeState)
            graph.add_node("validate_inputs", validate)
            graph.add_node("record_inputs", record)
            graph.add_edge(START, "validate_inputs")
            graph.add_edge("validate_inputs", "record_inputs")
            graph.add_edge("record_inputs", END)
            with tracing_context(enabled=False):
                graph.compile().invoke({"recorded": False})
        return self.get(request.intake_id)

    def record_evidence(self, evidence):
        intake = self.repository.get(evidence.intake_id)
        if not intake:
            raise LookupError("Entrada de ingeniería no encontrada")
        self._project(intake["case_id"])
        with (
            self.repository.store.lock(f"engineering:{evidence.intake_id}"),
            self.repository.store.lock(f"process:{intake['case_id']}"),
        ):
            if intake["operator"] != self.operator:
                raise ValueError("La entrada pertenece a otro responsable")
            evidence_sha256 = digest(evidence.model_dump(mode="json"))
            previous = self.repository.evidence(evidence.run_id)
            if previous:
                if (
                    previous["evidence_sha256"] != evidence_sha256
                    or previous["operator"] != self.operator
                ):
                    raise DeliveryConflict("El run_id ya corresponde a otra evidencia")
                return self.get(evidence.intake_id)
            request = EngineeringIntake.model_validate(intake["input"])
            self._upstream(request)
            if (
                self.repository.store.get(f"process:{intake['case_id']}")["iteration"]
                != intake["process_iteration"]
            ):
                raise DeliveryConflict(
                    "La iteración de ingeniería cambió; registrar una entrada nueva"
                )
            if evidence.input_sha256 != intake["input_sha256"] or sorted(
                [m.model_dump_json() for m in evidence.modules]
            ) != sorted([m.model_dump_json() for m in request.modules]):
                raise DeliveryConflict(
                    "La evidencia corresponde a otra entrada o versión de módulos"
                )
            now = self.repository.store.clock()
            for check in evidence.checks:
                if (
                    check.started_at is not None
                    and not intake["received_at"]
                    <= check.started_at.timestamp()
                    <= check.ended_at.timestamp()
                    <= now
                ):
                    raise ValueError(
                        "El intervalo técnico precede la recepción o termina en el futuro"
                    )
            prefix = f"https://github.com/{request.repository}/blob/{evidence.implementation_commit}/"
            if any(
                f.role == "implementation" and not f.reference.startswith(prefix)
                for f in evidence.files
            ):
                raise DeliveryConflict(
                    "La implementación pertenece a otro repositorio o commit"
                )
            files = self.files.read(evidence.files)
            self.repository.record(
                intake, evidence, evidence_sha256, self.operator, files
            )
        return self.get(evidence.intake_id)

    def catalog(self, intake_id):
        """Version the observed combinations, including failures; infer no support."""
        intake = self.repository.get(intake_id)
        if not intake or intake["operator"] != self.operator:
            raise ValueError("Entrada inexistente o de otro responsable")
        self._project(intake["case_id"])
        entries = []
        for run in self.repository.runs(intake_id):
            evidence = run["evidence"]
            entries.append(
                {
                    "run_id": run["run_id"],
                    "evidence_sha256": run["evidence_sha256"],
                    "modules": evidence["modules"],
                    "resources": evidence["resources"],
                    "versions": evidence["versions"],
                    "implementation_commit": evidence["implementation_commit"],
                    "implementation_tree_sha256": evidence[
                        "implementation_tree_sha256"
                    ],
                    "status": run["reported_status"],
                    "checks": evidence["checks"],
                    "reference": evidence["run_reference"],
                    "provenance": run["execution_verification"],
                    "limits": [
                        "Solo la combinación y el alcance local_emulator declarados; no acredita AWS real ni otras versiones."
                    ],
                }
            )
        content = {
            "schema_version": "1.0",
            "intake_id": str(intake_id),
            "revision": len(entries),
            "entries": entries,
        }
        return {**content, "sha256": digest(content)}

    def _validate_release(self, intake, release):
        request = EngineeringIntake.model_validate(intake["input"])
        if digest(request.model_dump(mode="json")) != intake["input_sha256"]:
            raise DeliveryConflict("El manifiesto de entrada no coincide con su hash")
        self._upstream(request, delivered=True)
        if release.input_sha256 != intake["input_sha256"]:
            raise DeliveryConflict("La entrega corresponde a otra entrada")
        expected_modules = sorted(m.model_dump_json() for m in request.modules)
        if (
            sorted(v.module.model_dump_json() for v in release.baseline_verifications)
            != expected_modules
        ):
            raise DeliveryConflict(
                "Verificar las aprobaciones de todos los baselines exactos"
            )
        if release.architect != request.architecture.approval.actor:
            raise DeliveryConflict(
                "La revisión no corresponde al arquitecto de la entrada"
            )
        prefix = f"https://github.com/{request.repository}/"
        if not re.fullmatch(
            re.escape(prefix) + r"pull/[1-9][0-9]*", release.pull_request
        ):
            raise DeliveryConflict("El PR debe pertenecer al repositorio del proyecto")
        if not release.review_reference.startswith(release.pull_request + "#"):
            raise DeliveryConflict("La aprobación debe referenciar la revisión del PR")
        if release.integration_reference != prefix + "commit/" + release.merge_commit:
            raise DeliveryConflict("La integración debe referenciar el commit de merge")
        for run_id in (release.local_run_id, release.ci_run_id):
            run = self.repository.evidence(run_id)
            if (
                not run
                or run["intake_id"] != intake["intake_id"]
                or run["reported_status"] != "passed"
            ):
                raise DeliveryConflict(
                    "La entrega requiere evidencias local y CI completas y exitosas"
                )
            evidence = run["evidence"]
            parsed = EngineeringEvidence.model_validate(evidence)
            if (
                not all(c.status == "passed" for c in parsed.checks)
                or parsed.input_sha256 != intake["input_sha256"]
                or str(parsed.intake_id) != intake["intake_id"]
                or str(parsed.run_id) != str(run_id)
                or run["files"] != [f.model_dump(mode="json") for f in parsed.files]
                or sorted(m.model_dump_json() for m in parsed.modules)
                != expected_modules
            ):
                raise DeliveryConflict(
                    "El manifiesto de la corrida no corresponde a la entrega"
                )
            if (
                evidence["implementation_commit"] != release.implementation_commit
                or evidence["implementation_tree_sha256"]
                != release.implementation_tree_sha256
                or digest(evidence) != run["evidence_sha256"]
            ):
                raise DeliveryConflict(
                    "La entrega y las corridas deben identificar el mismo código probado"
                )
            if run_id == release.ci_run_id and not re.fullmatch(
                re.escape(prefix) + r"actions/runs/[1-9][0-9]*",
                evidence["run_reference"],
            ):
                raise DeliveryConflict(
                    "La evidencia CI requiere la referencia de su ejecución en el proyecto"
                )
            for file in run["files"]:
                self._read_file(release.intake_id, file["sha256"])
        if self.repository.runs(release.intake_id)[-1]["run_id"] not in {
            str(release.local_run_id),
            str(release.ci_run_id),
        }:
            raise DeliveryConflict(
                "La entrega debe incorporar la última corrida registrada"
            )
        approval = next(
            (
                e["payload"]
                for e in self.repository.store.case_events(intake["case_id"])
                if e["kind"] == "process.transition"
                and e["payload"].get("event_id") == release.approval_event_id
            ),
            None,
        )
        if (
            not approval
            or (
                approval.get("kind"),
                approval.get("from_stage"),
                approval.get("to_stage"),
                approval.get("from_iteration"),
                approval.get("revision"),
                approval.get("artifact_sha256"),
                approval.get("actor"),
            )
            != (
                "stage.approved",
                5,
                6,
                intake["process_iteration"],
                release.revision,
                release.approval_digest(),
                release.architect,
            )
            or release.review_reference not in approval.get("evidence", [])
        ):
            raise DeliveryConflict(
                "Falta la aprobación registrada de la entrega exacta por el arquitecto"
            )
        state = self.repository.store.get(f"process:{intake['case_id']}")
        if state["stage"] != 6 or state["iteration"] != approval["to_iteration"]:
            raise DeliveryConflict(
                "La entrega no corresponde al ciclo vigente del proceso"
            )

    def record_release(self, release):
        intake = self.repository.get(release.intake_id)
        if not intake or intake["operator"] != self.operator:
            raise ValueError("Entrada inexistente o de otro responsable")
        self._project(intake["case_id"])
        with (
            self.repository.store.lock(f"engineering:{release.intake_id}"),
            self.repository.store.lock(f"process:{intake['case_id']}"),
        ):
            previous = self.repository.release(release.intake_id)
            value = release.model_dump(mode="json")
            if previous and previous["release"] != value:
                raise DeliveryConflict("La recepción ya tiene otra entrega definitiva")
            self._validate_release(intake, release)
            if not previous:
                self.repository.record_release(
                    intake, release, self.operator, self.catalog(release.intake_id)
                )
            self.repository.store.complete_phase(intake["case_id"], "stage-5")
            self.repository.store.phase(intake["case_id"], "stage-6", self.operator)
        return self.get(release.intake_id)

    def get(self, intake_id):
        intake = self.repository.get(intake_id)
        if not intake:
            raise LookupError("Entrada de ingeniería no encontrada")
        self._project(intake["case_id"])
        if intake["operator"] != self.operator:
            raise ValueError("La entrada pertenece a otro responsable")
        try:
            release = self.repository.release(intake_id)
            if release:
                parsed = EngineeringRelease.model_validate(release["release"])
                if (
                    parsed.approval_digest() != release["release_sha256"]
                    or str(parsed.intake_id) != intake["intake_id"]
                    or release["operator"] != self.operator
                    or release["case_id"] != intake["case_id"]
                    or release["catalog"] != self.catalog(intake_id)
                ):
                    raise DeliveryConflict(
                        "El respaldo de la entrega no coincide con su hash"
                    )
                self._validate_release(intake, parsed)
                current = True
            else:
                self._upstream(EngineeringIntake.model_validate(intake["input"]))
                current = (
                    self.repository.store.get(f"process:{intake['case_id']}")[
                        "iteration"
                    ]
                    == intake["process_iteration"]
                )
        except DeliveryConflict:
            current = False
        runs = self.repository.runs(intake_id)
        metrics = case_metrics(
            self.repository.store.metrics(intake["case_id"]),
            self.repository.store.clock(),
        )
        return {
            "intake": intake,
            "evidence": runs,
            "evidence_status": runs[-1]["reported_status"] if runs else "not_received",
            "upstream_current": current,
            "phase_metrics": next(
                p for p in metrics["phases"] if p["phase"] == "engineering"
            ),
            "review_status": "approved_recorded" if release and current else "pending",
            "integration_status": "merged_recorded" if release and current else "no_pr",
            "release": release,
            "catalog": self.catalog(intake_id),
            "blockers": (
                []
                if release and current
                else [
                    "Aprobación e integración del PR técnico pendientes.",
                    "Las referencias de aprobación de baselines requieren verificación externa.",
                ]
            )
            + (
                ["Faltan evidencias técnicas."]
                if not runs
                else (
                    [
                        "La última corrida informada tiene fallos o comprobaciones no ejecutadas."
                    ]
                    if runs[-1]["reported_status"] != "passed"
                    else []
                )
            )
            + (
                []
                if current
                else ["La entrada ya no corresponde al ciclo vigente del proceso."]
            ),
        }

    def read_file(self, intake_id, file_sha256):
        self.get(intake_id)  # Apply the same project/operator guard as receipt queries.
        return self._read_file(intake_id, file_sha256)

    def _read_file(self, intake_id, file_sha256):
        if not re.fullmatch(r"[a-f0-9]{64}", file_sha256):
            raise ValueError("SHA-256 inválido")
        file = self.repository.file(intake_id, file_sha256)
        if not file:
            raise LookupError("Archivo no encontrado en esta entrada")
        content = base64.b64decode(file["content_base64"])
        if sha256(content).hexdigest() != file_sha256:
            raise DeliveryConflict("El respaldo del archivo no coincide con su hash")
        return content
