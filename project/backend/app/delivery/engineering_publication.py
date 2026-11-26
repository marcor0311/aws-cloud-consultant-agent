"""Recoverable publication, verified integration and queued engineering handoff."""

from app.delivery.engineering_models import (
    EngineeringEvidence,
    EngineeringIntake,
    EngineeringRelease,
    digest,
)
from app.persistence.delivery import DeliveryConflict


class EngineeringPublicationService:
    def __init__(self, engineering, github, process):
        self.engineering, self.github, self.process = engineering, github, process
        self.store = engineering.repository.store

    def _run(self, intake, run_id):
        run = self.engineering.repository.evidence(run_id)
        if (
            not run
            or run["intake_id"] != intake["intake_id"]
            or run["reported_status"] != "passed"
        ):
            raise DeliveryConflict(
                "La operación requiere una corrida completa y exitosa de esta recepción"
            )
        if digest(run["evidence"]) != run["evidence_sha256"]:
            raise DeliveryConflict(
                "El manifiesto de la corrida no coincide con su hash"
            )
        evidence = EngineeringEvidence.model_validate(run["evidence"])
        if (
            digest(intake["input"]) != intake["input_sha256"]
            or evidence.input_sha256 != intake["input_sha256"]
            or str(evidence.run_id) != str(run_id)
            or str(evidence.intake_id) != intake["intake_id"]
            or not all(c.status == "passed" for c in evidence.checks)
            or run["files"] != [f.model_dump(mode="json") for f in evidence.files]
            or sorted(digest(m.model_dump(mode="json")) for m in evidence.modules)
            != sorted(digest(m) for m in intake["input"]["modules"])
        ):
            raise DeliveryConflict(
                "La corrida no acredita esta entrada y todos sus resultados"
            )
        for file in run["files"]:
            self.engineering._read_file(intake["intake_id"], file["sha256"])
        return run["evidence"]

    def publish(self, request):
        bundle = self.engineering.get(request.intake_id)
        intake = bundle["intake"]
        key = f"engineering-publication:{request.intake_id}"
        value = request.model_dump(mode="json")
        with (
            self.store.lock(f"engineering:{request.intake_id}"),
            self.store.lock(f"process:{intake['case_id']}"),
        ):
            previous = self.store.get(key)
            if previous and previous["request"] != value:
                raise DeliveryConflict(
                    "Esta recepción ya tiene otra solicitud de publicación"
                )
            inputs = EngineeringIntake.model_validate(intake["input"])
            self.engineering._upstream(inputs, delivered=bool(previous))
            state = self.store.get(f"process:{intake['case_id']}")
            if state["iteration"] != intake[
                "process_iteration"
            ] and not self.engineering.repository.release(request.intake_id):
                raise DeliveryConflict(
                    "La iteración cambió; registrar una recepción nueva"
                )
            evidence = self._run(intake, request.local_run_id)
            self.github.protection(inputs.repository)
            baselines = self.github.verify_baselines(intake["input"]["modules"])
            code = [f for f in evidence["files"] if f["role"] == "implementation"]
            for file in code:
                self.engineering._read_file(request.intake_id, file["sha256"])
            self.github.verify_files(
                inputs.repository, evidence["implementation_commit"], code
            )
            # Repeating after a lost response reconciles ref and PR by exact marker.
            pull = self.github.publish(
                inputs.repository, value, evidence, intake["input"]
            )
            record = {
                "request": value,
                "pull_request": pull,
                "baselines": baselines,
                "operator": self.engineering.operator,
                "case_id": intake["case_id"],
                "recorded_at": self.store.clock(),
            }
            self.store.put(key, "engineering-publication", record)
            return record

    def integrate(self, request):
        bundle = self.engineering.get(request.intake_id)
        intake = bundle["intake"]
        publication = self.store.get(f"engineering-publication:{request.intake_id}")
        if not publication or publication["operator"] != self.engineering.operator:
            raise DeliveryConflict("Publicar primero el PR de esta recepción")
        key = f"engineering-integration:{request.intake_id}"
        value = request.model_dump(mode="json")
        events = []
        release = None
        with self.store.lock(f"engineering:{request.intake_id}"):

            def gate(state):
                nonlocal release
                prior = self.store.get(key)
                if prior and prior["request"] != value:
                    raise DeliveryConflict(
                        "La integración ya tiene otra solicitud; conciliar antes de continuar"
                    )
                if state["iteration"] not in (
                    intake["process_iteration"],
                    intake["process_iteration"] + 1,
                ):
                    raise DeliveryConflict("La iteración del proceso cambió")
                token = f"engineering:{request.intake_id}"
                replay = any(
                    e["event_id"] == token + ":ready" for e in state["history"]
                )
                if not replay and (
                    state["stage"] != 5
                    or state["status"] != "awaiting_deliverable"
                    or request.revision <= state["revision"]
                ):
                    raise DeliveryConflict(
                        "El proceso no espera esta nueva entrega de ingeniería"
                    )
                inputs = EngineeringIntake.model_validate(intake["input"])
                local = self._run(intake, publication["request"]["local_run_id"])
                ci = self._run(intake, request.ci_run_id)
                if (
                    local["implementation_commit"] != ci["implementation_commit"]
                    or local["implementation_tree_sha256"]
                    != ci["implementation_tree_sha256"]
                ):
                    raise DeliveryConflict(
                        "Las corridas local y CI deben probar el mismo código"
                    )
                baselines = self.github.verify_baselines(intake["input"]["modules"])
                ci_receipt = self.github.verify_ci(inputs.repository, ci)
                # Validate complete run manifests/archives BEFORE any merge.
                candidate = EngineeringRelease(
                    intake_id=request.intake_id,
                    input_sha256=intake["input_sha256"],
                    revision=request.revision,
                    local_run_id=publication["request"]["local_run_id"],
                    ci_run_id=request.ci_run_id,
                    implementation_commit=ci["implementation_commit"],
                    implementation_tree_sha256=ci["implementation_tree_sha256"],
                    pull_request=publication["pull_request"]["url"],
                    base_branch="main",
                    merge_commit="0" * 40,
                    review_commit=ci["implementation_commit"],
                    architect=inputs.architecture.approval.actor,
                    review_reference=publication["pull_request"]["url"] + "#pending",
                    baseline_verifications=baselines,
                    branch_protection_reference=f"https://github.com/{inputs.repository}/settings/branches",
                    integration_reference=f"https://github.com/{inputs.repository}/commit/{'0' * 40}",
                    compatibility_limits=request.compatibility_limits,
                    approval_event_id=token + ":approved",
                )
                self.engineering._validate_release(
                    intake, candidate, require_approval=False
                )
                receipt = self.github.integrate(
                    inputs.repository,
                    publication["pull_request"],
                    ci,
                    candidate.architect,
                )
                release = EngineeringRelease.model_validate(
                    {
                        **candidate.model_dump(mode="json"),
                        **receipt,
                        "integration_reference": f"https://github.com/{inputs.repository}/commit/{receipt['merge_commit']}",
                    }
                )
                record = {
                    "request": value,
                    "release": release.model_dump(mode="json"),
                    "ci": ci_receipt,
                    "baselines": baselines,
                    "verified_at": self.store.clock(),
                    "verification": "github_api:commit_files; baseline_reviews; branch_protection; ci_status; architect_review; merge",
                }
                if prior and prior["release"] != record["release"]:
                    raise DeliveryConflict(
                        "La evidencia externa cambió desde la integración registrada"
                    )
                self.store.put(key, "engineering-integration", record)
                common = {
                    "stage": 5,
                    "iteration": intake["process_iteration"],
                    "actor": release.architect,
                    "origin": "internal",
                    "revision": release.revision,
                    "artifact_sha256": release.approval_digest(),
                    "evidence": [
                        release.review_reference,
                        release.integration_reference,
                    ],
                }
                events.extend(
                    [
                        {
                            **common,
                            "event_id": token + ":ready",
                            "kind": "deliverable.ready",
                        },
                        {
                            **common,
                            "event_id": token + ":approved",
                            "kind": "stage.approved",
                        },
                    ]
                )

            self.process.apply_sequence(intake["case_id"], events, gate)
        # Release service revalidates the resulting workflow before recording the
        # final handoff. Its outbox is committed atomically with the release.
        return self.engineering.record_release(release)
