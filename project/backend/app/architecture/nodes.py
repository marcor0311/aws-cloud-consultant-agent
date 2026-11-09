"""Deterministic architecture validation and explicit human review."""

from langgraph.types import interrupt

from app.architecture.models import ArchitectureFinOpsHandoff, ArchitecturePackage


class ArchitectureNodes:
    def __init__(self, catalog):
        self.catalog = catalog

    def validate(self, state):
        package = ArchitecturePackage.model_validate(state["package"])
        self.catalog.validate(package.baselines)
        return {
            "package": package.model_dump(mode="json"),
            "documents": package.artifacts(),
            "revision": 1,
            "status": "awaiting_review",
            "parent_revision": None,
            "correction_request_id": "",
            "correction_history": [],
            "revision_history": [],
            "approval_history": [],
            "handoff_history": [],
        }

    def review(self, state):
        response = interrupt(
            {
                "action": "architect_review",
                "revision": state["revision"],
                "artifact_sha256": state["artifact_sha256"],
                "package": state["package"],
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
        decision = response["decision"]
        approval = {
            "revision": state["revision"],
            "artifact_sha256": state["artifact_sha256"],
            "decision": decision,
            "feedback": response.get("feedback", ""),
        }
        revision_record = {
            "revision": state["revision"],
            "parent_revision": state.get("parent_revision"),
            "correction_request_id": state.get("correction_request_id", ""),
            "artifact_sha256": state["artifact_sha256"],
            "package": state["package"],
            "documents": state["documents"],
            "decision": decision,
        }
        approvals = [
            item
            for item in state.get("approval_history", [])
            if not (
                item["revision"] == approval["revision"]
                and item["artifact_sha256"] == approval["artifact_sha256"]
            )
        ]
        revisions = [
            item
            for item in state.get("revision_history", [])
            if item["revision"] != revision_record["revision"]
        ]
        return {
            "decision": response["decision"],
            "feedback": response.get("feedback", ""),
            "status": "approved"
            if decision == "approve"
            else "changes_requested",
            "approval_history": [*approvals, approval],
            "revision_history": [*revisions, revision_record],
        }

    def handoff(self, state):
        package = ArchitecturePackage.model_validate(state["package"])
        blocking_reasons = package.finops_blocking_reasons()
        handoff = ArchitectureFinOpsHandoff(
            handoff_status="blocked" if blocking_reasons else "ready",
            blocking_reasons=blocking_reasons,
            revision=state["revision"],
            artifact_sha256=state["artifact_sha256"],
            source_issue=package.source_issue,
            architecture_schema_version=package.schema_version,
            architecture=package,
            economic_contract=package.economic_contract,
            documents=sorted(state["documents"]),
        )
        handoff_payload = handoff.model_dump(mode="json")
        previous = [
            item
            for item in state.get("handoff_history", [])
            if item["revision"] != state["revision"]
        ]
        return {
            "status": (
                "blocked_for_finops_inputs"
                if blocking_reasons
                else "ready_for_finops"
            ),
            "handoff": handoff_payload,
            "handoff_history": [*previous, handoff_payload],
        }
