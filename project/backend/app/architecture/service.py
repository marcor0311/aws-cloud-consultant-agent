"""Application service for architecture revisions and handoff to FinOps."""

import hashlib
import json
from contextlib import nullcontext
from threading import RLock

from app.architecture.corrections import FinOpsCorrectionRequest
from app.architecture.diagram_renderer import AwsDacRenderer
from app.architecture.models import ArchitecturePackage
from app.architecture.project_repository import ProjectRepositoryBridge


class ArchitectureService:
    def __init__(
        self,
        graph,
        catalog,
        store=None,
        process=None,
        architect_id="architect",
        project_repository=None,
        diagram_renderer=None,
    ):
        self.graph, self.catalog, self.store = graph, catalog, store
        self.process, self.architect_id = process, architect_id
        self.project_repository = project_repository or ProjectRepositoryBridge()
        self.diagram_renderer = diagram_renderer or AwsDacRenderer()
        self.project_contexts = {}
        self.lock = RLock()

    @staticmethod
    def thread_id(case_id):
        if not isinstance(case_id, str) or not 1 <= len(case_id) <= 120:
            raise ValueError("Expediente inválido.")
        return f"architecture:{case_id}"

    @staticmethod
    def digest(package):
        return hashlib.sha256(
            json.dumps(package, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def get(self, case_id):
        snapshot = self.graph.inspect(self.thread_id(case_id))
        if not snapshot.state:
            raise ValueError("El expediente no tiene un diseño de arquitectura.")
        return {"state": snapshot.state, "pending": snapshot.pending}

    def catalog_modules(self):
        return self.catalog.modules()

    def read_project_handoff(self, handoff):
        context = self.project_repository.read(handoff)
        key = f"architecture-project-context:{context['case_id']}"
        previous = self.store.get(key) if self.store else self.project_contexts.get(key)
        if previous and previous != context:
            raise ValueError("El expediente ya tiene otra entrega aprobada del agente 2.")
        if not previous:
            if self.store:
                self.store.put(key, "architecture_project_context", context)
            else:
                self.project_contexts[key] = context
        return context

    def publish_to_project(self, case_id):
        state = self.get(case_id)["state"]
        if state.get("status") != "ready_for_finops":
            raise ValueError("Solo se publica una revisión aprobada y lista para FinOps.")
        key = f"architecture-project-context:{case_id}"
        context = self.store.get(key) if self.store else self.project_contexts.get(key)
        if not context:
            raise ValueError("El expediente no tiene una entrega de proyecto validada.")
        documents = dict(state["documents"])
        if state["package"].get("schema_version") == "1.2":
            source = documents.get("architecture.aws-dac.yaml")
            if not source:
                raise ValueError("La revisión 1.2 no contiene el YAML de diagrama.")
            documents["architecture.png"] = self.diagram_renderer.render_bytes(source)
        result = self.project_repository.publish(
            context["repository_path"], state["revision"], documents
        )
        if self.store:
            record_key = f"architecture-publication:{case_id}:{state['revision']}"
            previous = self.store.get(record_key)
            if previous:
                previous_content = {k: v for k, v in previous.items() if k != "status"}
                result_content = {k: v for k, v in result.items() if k != "status"}
                if previous_content != result_content:
                    raise ValueError("La publicación registrada es inmutable.")
            if not previous:
                self.store.put(record_key, "architecture_publication", result)
        return result

    def history(self, case_id):
        state = self.get(case_id)["state"]
        return {
            "case_id": case_id,
            "current_revision": state["revision"],
            "current_status": state["status"],
            "revisions": state.get("revision_history", []),
            "corrections": state.get("correction_history", []),
            "approvals": state.get("approval_history", []),
            "handoffs": state.get("handoff_history", []),
        }

    def get_finops_handoff(self, case_id, revision):
        state = self.get(case_id)["state"]
        handoff = next(
            (
                item
                for item in state.get("handoff_history", [])
                if item["revision"] == revision
            ),
            None,
        )
        if not handoff:
            raise ValueError("No existe un handoff para esa revisión.")
        if revision != state["revision"] or state.get("status") != "ready_for_finops":
            raise ValueError("Solo se entrega la revisión vigente aprobada.")
        if handoff["handoff_status"] != "ready":
            raise ValueError("El handoff tiene insumos económicos pendientes.")
        return handoff

    def start(self, case_id, input_id, package):
        validated = ArchitecturePackage.model_validate(package)
        payload = validated.model_dump(mode="json")
        fingerprint = self.digest(payload)
        guard = (
            self.store.lock(f"architecture:{case_id}") if self.store else nullcontext()
        )
        with self.lock, guard:
            context_key = f"architecture-project-context:{case_id}"
            context = (
                self.store.get(context_key)
                if self.store
                else self.project_contexts.get(context_key)
            )
            if context:
                if input_id != context["input_id"]:
                    raise ValueError("La entrada no corresponde al commit aprobado.")
                if validated.project_id != context["project_id"]:
                    raise ValueError("La arquitectura corresponde a otro proyecto.")
                if validated.source_issue != context["architecture_issue_url"]:
                    raise ValueError("La arquitectura corresponde a otro issue.")
                sources = {item["path"] for item in context["documents"]}
                if not all(item.source in sources for item in validated.requirements):
                    raise ValueError(
                        "Cada requisito debe referenciar un insumo aprobado del proyecto."
                    )
            previous = self.graph.inspect(self.thread_id(case_id)).state
            if previous:
                if (
                    previous.get("input_id") != input_id
                    or previous.get("input_hash") != fingerprint
                ):
                    raise ValueError(
                        "El expediente ya tiene otra entrada de arquitectura."
                    )
                return self.get(case_id)
            if self.process:
                process = self.process.get(case_id)["state"]
                if process["stage"] != 3 or process["status"] != "awaiting_deliverable":
                    raise ValueError(
                        "El proceso no está esperando el diseño de arquitectura."
                    )
            self.graph.start(
                self.thread_id(case_id),
                {
                    "case_id": case_id,
                    "input_id": input_id,
                    "input_hash": fingerprint,
                    "package": payload,
                    "artifact_sha256": fingerprint,
                },
            )
            self._sync(case_id)
            return self.get(case_id)

    def replace(self, case_id, revision, package):
        validated = ArchitecturePackage.model_validate(package)
        payload = validated.model_dump(mode="json")
        with (
            self.lock,
            self.store.lock(f"architecture:{case_id}") if self.store else nullcontext(),
        ):
            current = self.get(case_id)
            state = current["state"]
            if (
                state.get("status") != "changes_requested"
                or state["revision"] != revision
            ):
                raise ValueError("La revisión no está esperando correcciones.")
            self.catalog.validate(validated.baselines)
            new_revision = revision + 1
            digest = self.digest(payload)
            self.graph.update(
                self.thread_id(case_id),
                {
                    "package": payload,
                    "documents": validated.artifacts(),
                    "revision": new_revision,
                    "parent_revision": revision,
                    "status": "awaiting_review",
                    "decision": "",
                    "artifact_sha256": digest,
                },
                after_step="validate_architecture",
            )
            self.graph.continue_run(self.thread_id(case_id))
            self._sync(case_id)
            return self.get(case_id)

    def request_finops_correction(self, case_id, request):
        correction = FinOpsCorrectionRequest.model_validate(request)
        payload = correction.model_dump(mode="json")
        request_hash = self.digest(payload)
        with (
            self.lock,
            self.store.lock(f"architecture:{case_id}") if self.store else nullcontext(),
        ):
            current = self.get(case_id)
            state = current["state"]
            previous = next(
                (
                    item
                    for item in state.get("correction_history", [])
                    if item["request"]["request_id"] == correction.request_id
                ),
                None,
            )
            if previous:
                if previous["request_hash"] != request_hash:
                    raise ValueError(
                        "El identificador de corrección ya tiene otro contenido."
                    )
                return {"duplicate": True, **current}
            if state.get("status") != "ready_for_finops":
                raise ValueError(
                    "Solo una arquitectura entregada a FinOps puede reabrirse."
                )
            package = ArchitecturePackage.model_validate(state["package"])
            if correction.architecture_id != case_id:
                raise ValueError("La corrección corresponde a otra arquitectura.")
            if correction.project_id != package.project_id:
                raise ValueError("La corrección corresponde a otro proyecto.")
            if correction.source_revision != state["revision"]:
                raise ValueError("La corrección no corresponde a la revisión entregada.")
            known_resources = {item.resource_id for item in package.resources}
            if not set(correction.affected_resources) <= known_resources:
                raise ValueError("La corrección referencia recursos desconocidos.")
            dimensions = {
                (pricing.resource_id, dimension.dimension_id)
                for pricing in package.economic_contract.pricing_inputs
                for dimension in pricing.dimensions
            }
            affected_dimensions = {
                (item.resource_id, item.dimension_id)
                for item in correction.affected_dimensions
            }
            if not affected_dimensions <= dimensions:
                raise ValueError("La corrección referencia dimensiones desconocidas.")
            record = {"request_hash": request_hash, "request": payload}
            self.graph.update(
                self.thread_id(case_id),
                {
                    "status": "finops_changes_requested",
                    "decision": "",
                    "feedback": correction.reason,
                    "correction_request_id": correction.request_id,
                    "correction_request": payload,
                    "correction_history": [
                        *state.get("correction_history", []),
                        record,
                    ],
                },
                after_step="handoff_finops",
            )
            self._sync(case_id)
            return {"duplicate": False, **self.get(case_id)}

    def revise_from_finops(self, case_id, request_id, package):
        validated = ArchitecturePackage.model_validate(package)
        payload = validated.model_dump(mode="json")
        payload_hash = self.digest(payload)
        with (
            self.lock,
            self.store.lock(f"architecture:{case_id}") if self.store else nullcontext(),
        ):
            current = self.get(case_id)
            state = current["state"]
            if state.get("status") != "finops_changes_requested":
                if state.get("correction_request_id") == request_id:
                    if self.digest(state["package"]) == payload_hash:
                        return {"duplicate": True, **current}
                    raise ValueError(
                        "La solicitud ya fue aplicada con otra arquitectura."
                    )
                raise ValueError("La arquitectura no espera una corrección de FinOps.")
            if state.get("correction_request_id") != request_id:
                raise ValueError("La solicitud de corrección no coincide.")
            previous = ArchitecturePackage.model_validate(state["package"])
            if validated.project_id != previous.project_id:
                raise ValueError("Una corrección no puede cambiar el proyecto.")
            if validated.source_issue != previous.source_issue:
                raise ValueError("Una corrección no puede cambiar el issue de origen.")
            if payload_hash == self.digest(state["package"]):
                raise ValueError(
                    "La corrección debe modificar la revisión arquitectónica."
                )
            self.catalog.validate(validated.baselines)
            source_revision = state["revision"]
            new_revision = source_revision + 1
            digest = payload_hash
            self.graph.update(
                self.thread_id(case_id),
                {
                    "package": payload,
                    "documents": validated.artifacts(),
                    "revision": new_revision,
                    "parent_revision": source_revision,
                    "status": "awaiting_review",
                    "decision": "",
                    "feedback": "",
                    "artifact_sha256": digest,
                    "handoff": {},
                },
                after_step="validate_architecture",
            )
            self.graph.continue_run(self.thread_id(case_id))
            self._sync(case_id)
            return {"duplicate": False, **self.get(case_id)}

    def review(self, case_id, revision, artifact_sha256, decision, feedback=""):
        if decision not in {"approve", "revise"}:
            raise ValueError("La decisión debe ser approve o revise.")
        if decision == "revise" and not feedback.strip():
            raise ValueError("Indicar los ajustes solicitados.")
        with (
            self.lock,
            self.store.lock(f"architecture:{case_id}") if self.store else nullcontext(),
        ):
            current = self.get(case_id)
            state = current["state"]
            if (
                state.get("status") != "awaiting_review"
                or state["revision"] != revision
                or state["artifact_sha256"] != artifact_sha256
            ):
                raise ValueError("Aprobar únicamente la revisión pendiente exacta.")
            self.graph.resume(
                self.thread_id(case_id),
                {"decision": decision, "feedback": feedback},
            )
            self._sync(case_id)
            return self.get(case_id)

    def _sync(self, case_id):
        if not self.store:
            return
        state = self.get(case_id)["state"]
        revision = state["revision"]
        self.store.phase(case_id, "stage-3", self.architect_id)
        artifact_key = f"architecture-artifact:{case_id}:{revision}"
        artifact = {
            "case_id": case_id,
            "revision": revision,
            "artifact_sha256": state["artifact_sha256"],
            "package": state["package"],
            "documents": state["documents"],
        }
        existing = self.store.get(artifact_key)
        if existing and existing != artifact:
            raise ValueError("Una revisión persistida es inmutable.")
        if not existing:
            self.store.put(artifact_key, "architecture_artifact", artifact)
        for correction in state.get("correction_history", []):
            request = correction["request"]
            key = f"architecture-correction:{case_id}:{request['request_id']}"
            existing = self.store.get(key)
            if existing and existing != correction:
                raise ValueError("Una solicitud de corrección persistida es inmutable.")
            if not existing:
                self.store.put(key, "architecture_correction", correction)
            self.store.event(
                f"architecture-correction:{case_id}:{request['request_id']}",
                case_id,
                "architecture.finops_correction_requested",
                request,
            )
        for approval in state.get("approval_history", []):
            self.store.event(
                f"architecture-approval:{case_id}:{approval['revision']}:"
                f"{approval['artifact_sha256']}",
                case_id,
                "approval.decided",
                {"actor": self.architect_id, **approval},
            )
        for handoff_payload in state.get("handoff_history", []):
            key = f"architecture-handoff:{case_id}:{handoff_payload['revision']}"
            existing = self.store.get(key)
            if existing and existing != handoff_payload:
                raise ValueError("Un handoff persistido es inmutable.")
            if not existing:
                self.store.put(key, "architecture_handoff", handoff_payload)
        if state["status"] == "awaiting_review":
            self.store.event(
                f"architecture-review:{case_id}:{revision}",
                case_id,
                "approval.requested",
                {"actor": self.architect_id, "revision": revision},
            )
        if state["status"] == "ready_for_finops":
            self.store.complete_phase(case_id, "stage-3")
            self.store.create_handoff(
                f"{case_id}:stage-3:stage-4:v{revision}",
                case_id,
                self.architect_id,
                "finops-agent",
                "stage-3",
                "stage-4",
                revision=revision,
                artifact_sha256=state["artifact_sha256"],
            )
            if self.process:
                evidence = [f"architecture-artifact:{case_id}:{revision}"]
                current = self.process.get(case_id)["state"]
                if (
                    current["stage"] == 3
                    and current["status"] == "awaiting_deliverable"
                ):
                    self.process.internal(
                        case_id,
                        f"architecture.ready:{revision}:{state['artifact_sha256']}",
                        "deliverable.ready",
                        revision=revision,
                        artifact_sha256=state["artifact_sha256"],
                        evidence=evidence,
                    )
                current = self.process.get(case_id)["state"]
                if current["stage"] == 3 and current["status"] == "awaiting_review":
                    self.process.internal(
                        case_id,
                        f"architecture.approved:{revision}:{state['artifact_sha256']}",
                        "stage.approved",
                        revision=revision,
                        artifact_sha256=state["artifact_sha256"],
                        evidence=evidence,
                    )
