"""Application service for architecture revisions and handoff to FinOps."""

import base64
import hashlib
import json
from contextlib import contextmanager, nullcontext
from threading import RLock

from app.architecture.corrections import FinOpsCorrectionRequest
from app.architecture.diagram_renderer import AwsDacRenderer
from app.architecture.github_delivery import (
    GitHubApprovalReceipt,
    GitHubFinOpsIssueReceipt,
    GitHubPublicationPlan,
    GitHubPullRequestReceipt,
)
from app.architecture.metrics import FinOpsHandoffAcceptance
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
        github_required=False,
    ):
        self.graph, self.catalog, self.store = graph, catalog, store
        self.process, self.architect_id = process, architect_id
        self.project_repository = project_repository or ProjectRepositoryBridge()
        self.diagram_renderer = diagram_renderer or AwsDacRenderer()
        self.github_required = github_required
        self.project_contexts = {}
        self.lock = RLock()

    @contextmanager
    def _agent_work(self, case_id, operation):
        """Measure real execution only; human and external waits remain separate."""
        if not self.store:
            yield
            return
        session_id = self.store.start_work(
            case_id,
            "stage-3",
            self.architect_id,
            "agent",
            issue_url=operation,
        )
        try:
            yield
        finally:
            self.store.stop_work(session_id, self.architect_id)

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

    def metrics(self, case_id):
        """Return auditable Architecture metrics without inferring missing work."""
        if not self.store:
            raise ValueError("Las métricas requieren persistencia.")
        self.get(case_id)
        stored = self.store.metrics(case_id)
        phase = next(
            (item for item in stored["phases"] if item["phase"] == "stage-3"),
            None,
        )
        events = self.store.case_events(case_id)
        requested = {
            item["payload"].get("revision"): item["at"]
            for item in events
            if item["kind"] == "approval.requested"
        }
        human_decisions = []
        for item in events:
            if item["kind"] != "approval.decided":
                continue
            revision = item["payload"].get("revision")
            start = requested.get(revision)
            if start is not None:
                human_decisions.append(
                    {
                        "revision": revision,
                        "requested_at": start,
                        "decided_at": item["at"],
                        "decision": item["payload"].get("decision"),
                        "seconds": max(0, item["at"] - start),
                    }
                )
        handoffs = [
            item
            for item in stored["handoffs"]
            if item["from_phase"] == "stage-3" and item["to_phase"] == "stage-4"
        ]
        agent_seconds = (
            phase["recorded_effort_seconds"]["agent"] if phase else 0.0
        )
        human_seconds = sum(item["seconds"] for item in human_decisions)
        lead_seconds = phase["lead_seconds"] if phase else 0.0
        intervals = [
            (item["requested_at"], item["decided_at"])
            for item in human_decisions
        ]
        intervals.extend(
            (item["started_at"], item["ended_at"])
            for item in stored["sessions"]
            if item["phase"] == "stage-3"
            and item["actor_type"] == "agent"
            and item["ended_at"] is not None
        )
        recorded_union = 0.0
        last_end = float("-inf")
        for start, end in sorted(intervals):
            recorded_union += max(0, end - max(start, last_end))
            last_end = max(last_end, end)
        return {
            "contract_version": "1.0",
            "case_id": case_id,
            "lead_time_seconds": lead_seconds,
            "process_time_seconds": {
                "agent": agent_seconds,
                "human_decision": human_seconds,
                "total_recorded_union": recorded_union,
            },
            "wait_time_seconds": max(0, lead_seconds - recorded_union),
            "rework_cycles": stored["rework_cycles"],
            "human_decisions": human_decisions,
            "finops_handoffs": handoffs,
            "coverage": (
                "agent sessions and approval wall time are measured; unrecorded time "
                "is reported as wait and is never inferred as work"
            ),
        }

    def accept_finops_handoff(self, case_id, receipt):
        """Persist FinOps acceptance of the exact current handoff, idempotently."""
        if not self.store:
            raise ValueError("La aceptación FinOps requiere persistencia.")
        validated = FinOpsHandoffAcceptance.model_validate(receipt)
        if validated.case_id != case_id:
            raise ValueError("La aceptación FinOps corresponde a otro expediente.")
        handoff = self.get_finops_handoff(case_id, validated.revision)
        if handoff["artifact_sha256"] != validated.artifact_sha256:
            raise ValueError("La aceptación FinOps no corresponde al artefacto vigente.")
        handoff_id = f"{case_id}:stage-3:stage-4:v{validated.revision}"
        persisted = self.store.handoff(handoff_id)
        if not persisted:
            raise ValueError("La entrega persistida a FinOps no existe.")
        if validated.accepted_at.timestamp() < persisted["created_at"]:
            raise ValueError("La aceptación FinOps precede a la entrega persistida.")
        key = f"architecture-finops-acceptance:{case_id}:{validated.revision}"
        payload = validated.model_dump(mode="json")
        previous = self.store.get(key)
        if previous and previous != payload:
            raise ValueError("La revisión ya tiene otra aceptación FinOps.")
        if not previous:
            self.store.accept_handoff(
                handoff_id,
                validated.accepted_by,
                validated.accepted_at.timestamp(),
            )
            self.store.put(key, "architecture_finops_acceptance", payload)
            self.store.event(
                f"architecture-finops-accepted:{case_id}:{validated.revision}",
                case_id,
                "architecture.finops_handoff_accepted",
                payload,
            )
        return {"duplicate": bool(previous), "receipt": payload}

    def prepare_github_publication(self, case_id):
        if not self.store:
            raise ValueError("La publicación GitHub requiere persistencia.")
        state = self.get(case_id)["state"]
        if state.get("status") != "ready_for_finops":
            raise ValueError("Solo una arquitectura aprobada puede preparar su PR.")
        context = self.store.get(f"architecture-project-context:{case_id}")
        if not context:
            raise ValueError("Falta la entrega validada del repositorio del proyecto.")
        revision = state["revision"]
        documents = dict(state["documents"])
        if state["package"].get("schema_version") == "1.2":
            source = documents.get("architecture.aws-dac.yaml")
            if not source:
                raise ValueError("La revisión 1.2 no contiene el YAML de diagrama.")
            documents["architecture.png"] = self.diagram_renderer.render_bytes(source)
        manifest = {
            "contract_version": "1.0",
            "revision": revision,
            "files": [
                {
                    "path": name,
                    "sha256": hashlib.sha256(
                        content.encode("utf-8")
                        if isinstance(content, str)
                        else content
                    ).hexdigest(),
                }
                for name, content in sorted(documents.items())
            ],
        }
        documents["manifest.json"] = json.dumps(manifest, indent=2) + "\n"
        prefix = f"docs/03-architecture/versions/v{revision:03d}"
        files = []
        for name, content in sorted(documents.items()):
            raw = content.encode("utf-8") if isinstance(content, str) else content
            files.append(
                {
                    "path": f"{prefix}/{name}",
                    "encoding": "utf-8" if isinstance(content, str) else "base64",
                    "content": (
                        content
                        if isinstance(content, str)
                        else base64.b64encode(content).decode("ascii")
                    ),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
        package = ArchitecturePackage.model_validate(state["package"])
        plan = GitHubPublicationPlan(
            case_id=case_id,
            project_id=package.project_id,
            revision=revision,
            artifact_sha256=state["artifact_sha256"],
            repository_url=context["repository_url"].removesuffix(".git"),
            source_issue_url=context["architecture_issue_url"],
            base_commit=context["source_commit"],
            branch=f"agent3/{package.project_id}/architecture-v{revision:03d}",
            commit_message=f"docs(architecture): publish revision {revision}",
            pull_request_title=f"[Arquitectura] {package.project_id} v{revision:03d}",
            pull_request_body=(
                f"Publica la revisión {revision} de Arquitectura.\n\n"
                f"Issue de origen: {package.source_issue}\n\n"
                f"SHA-256 del artefacto: `{state['artifact_sha256']}`\n\n"
                "Requiere aprobación humana explícita; cerrar el PR no sustituye la revisión."
            ),
            files=files,
        ).model_dump(mode="json")
        plan_sha256 = self.digest(plan)
        record = {"plan_sha256": plan_sha256, "plan": plan}
        key = f"architecture-github-plan:{case_id}:{revision}"
        previous = self.store.get(key)
        if previous and previous != record:
            raise ValueError("El plan GitHub de la revisión es inmutable.")
        if not previous:
            self.store.put(key, "architecture_github_plan", record)
        return record

    def register_github_pull_request(self, case_id, receipt):
        validated = GitHubPullRequestReceipt.model_validate(receipt)
        plan_record = self.store.get(
            f"architecture-github-plan:{case_id}:{self.get(case_id)['state']['revision']}"
        )
        if not plan_record or validated.plan_sha256 != plan_record["plan_sha256"]:
            raise ValueError("El recibo no corresponde al plan GitHub vigente.")
        plan = plan_record["plan"]
        if (
            validated.repository_url != plan["repository_url"]
            or validated.branch != plan["branch"]
            or validated.base_branch != plan["base_branch"]
            or validated.base_commit != plan["base_commit"]
            or not validated.pull_request_url.startswith(plan["repository_url"] + "/pull/")
        ):
            raise ValueError("El PR no corresponde al repositorio y rama planificados.")
        expected_files = {item["path"]: item["sha256"] for item in plan["files"]}
        actual_files = {item.get("path"): item.get("sha256") for item in validated.files}
        if actual_files != expected_files:
            raise ValueError("El commit del PR no contiene los artefactos aprobados.")
        key = f"architecture-github-pr:{case_id}:{plan['revision']}"
        payload = validated.model_dump(mode="json")
        previous = self.store.get(key)
        if previous and previous != payload:
            raise ValueError("La revisión ya tiene otro PR registrado.")
        if not previous:
            self.store.put(key, "architecture_github_pr", payload)
        return {"duplicate": bool(previous), "receipt": payload}

    def register_github_approval(self, case_id, receipt):
        validated = GitHubApprovalReceipt.model_validate(receipt)
        revision = self.get(case_id)["state"]["revision"]
        plan = self.store.get(f"architecture-github-plan:{case_id}:{revision}")
        pr = self.store.get(f"architecture-github-pr:{case_id}:{revision}")
        if not plan or not pr:
            raise ValueError("Primero se debe registrar el PR de Arquitectura.")
        if (
            validated.plan_sha256 != plan["plan_sha256"]
            or validated.pull_request_url != pr["pull_request_url"]
            or validated.head_sha != pr["commit_sha"]
            or validated.source_issue_url != plan["plan"]["source_issue_url"]
        ):
            raise ValueError("La aprobación no corresponde al PR y commit exactos.")
        key = f"architecture-github-approval:{case_id}:{revision}"
        payload = validated.model_dump(mode="json")
        previous = self.store.get(key)
        if previous and previous != payload:
            raise ValueError("La revisión ya tiene otra aprobación GitHub.")
        if not previous:
            self.store.put(key, "architecture_github_approval", payload)
        self._sync(case_id)
        return {"duplicate": bool(previous), "receipt": payload}

    def prepare_finops_issue(self, case_id, assignee):
        if not isinstance(assignee, str) or not assignee.strip():
            raise ValueError("Indicar el usuario GitHub responsable de FinOps.")
        state = self.get(case_id)["state"]
        revision = state["revision"]
        approval = self.store.get(f"architecture-github-approval:{case_id}:{revision}")
        plan = self.store.get(f"architecture-github-plan:{case_id}:{revision}")
        if not approval or not plan:
            raise ValueError("El PR de Arquitectura todavía no está aprobado y fusionado.")
        package = state["package"]
        handoff = self.get_finops_handoff(case_id, revision)
        budget = package["economic_contract"]["budget"]
        assumptions = "; ".join(
            f"{item['resource_id']}: {', '.join(item['sizing_assumptions'])}"
            for item in package["resources"]
        )
        body = (
            f"Arquitectura aprobada: {approval['pull_request_url']}\n\n"
            f"Merge commit: `{approval['merge_commit_sha']}`\n\n"
            f"Región: `{package['region']}`\n\n"
            f"Recursos: {', '.join(item['resource_id'] for item in package['resources'])}\n\n"
            f"Módulos: {', '.join(item['module_id'] for item in package['baselines']) or 'ninguno'}\n\n"
            f"Presupuesto: {budget['status']}"
            + (
                f" {budget['amount']} {budget['currency']} por {budget['period']}"
                if budget["status"] == "known"
                else ""
            )
            + "\n\n"
            f"Supuestos: {assumptions}\n\n"
            f"Revisión: {revision}; artefacto: `{state['artifact_sha256']}`."
        )
        draft = {
            "contract_version": "1.0",
            "plan_sha256": plan["plan_sha256"],
            "repository_url": plan["plan"]["repository_url"],
            "title": f"[FinOps] {package['project_id']} arquitectura v{revision:03d}",
            "body": body,
            "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "labels": ["finops", "architecture-approved"],
            "assignees": [assignee.strip()],
            "handoff": handoff,
        }
        key = f"architecture-finops-issue-draft:{case_id}:{revision}"
        previous = self.store.get(key)
        if previous and previous != draft:
            raise ValueError("El borrador FinOps de la revisión es inmutable.")
        if not previous:
            self.store.put(key, "architecture_finops_issue_draft", draft)
        return draft

    def register_finops_issue(self, case_id, receipt):
        validated = GitHubFinOpsIssueReceipt.model_validate(receipt)
        revision = self.get(case_id)["state"]["revision"]
        draft = self.store.get(
            f"architecture-finops-issue-draft:{case_id}:{revision}"
        )
        if not draft:
            raise ValueError("Primero se debe preparar el issue FinOps.")
        if (
            validated.plan_sha256 != draft["plan_sha256"]
            or validated.body_sha256 != draft["body_sha256"]
            or not validated.issue_url.startswith(draft["repository_url"] + "/issues/")
            or validated.assignees != draft["assignees"]
        ):
            raise ValueError("El issue FinOps no corresponde al borrador aprobado.")
        key = f"architecture-finops-issue:{case_id}:{revision}"
        payload = validated.model_dump(mode="json")
        previous = self.store.get(key)
        if previous and previous != payload:
            raise ValueError("La revisión ya tiene otro issue FinOps.")
        if not previous:
            self.store.put(key, "architecture_finops_issue", payload)
        return {"duplicate": bool(previous), "receipt": payload}

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
        if self.github_required and self.store:
            approval = self.store.get(
                f"architecture-github-approval:{case_id}:{revision}"
            )
            if not approval:
                raise ValueError("El handoff espera aprobación y merge del PR GitHub.")
        return handoff

    def start(self, case_id, input_id, package):
        validated = ArchitecturePackage.model_validate(package)
        payload = validated.model_dump(mode="json")
        fingerprint = self.digest(payload)
        guard = (
            self.store.lock(f"architecture:{case_id}") if self.store else nullcontext()
        )
        with self.lock, guard, self._agent_work(case_id, "start"):
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
            self._agent_work(case_id, "replace"),
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
            self._agent_work(case_id, "finops-correction-request"),
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
            self._agent_work(case_id, "finops-revision"),
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
            self._agent_work(case_id, "human-review-recording"),
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
        if state["status"] == "finops_changes_requested":
            self.store.reopen_phase(case_id, "stage-3")
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
            if self.github_required and not self.store.get(
                f"architecture-github-approval:{case_id}:{revision}"
            ):
                return
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
