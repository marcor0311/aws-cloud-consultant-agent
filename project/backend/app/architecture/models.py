"""Strict, versioned deliverable produced by the Cloud Architecture Agent."""

import json
import re
from decimal import Decimal
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.architecture.economics import EconomicContract
from app.architecture.topology import ArchitectureTopology


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Requirement(Contract):
    requirement_id: str = Field(pattern=r"^REQ-[0-9]{3}$")
    description: str = Field(min_length=1, max_length=1000)
    source: str = Field(min_length=1, max_length=500)


class ResourceDecision(Contract):
    resource_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    aws_service: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=1000)
    dependencies: list[str] = Field(default_factory=list, max_length=30)
    sizing_assumptions: list[str] = Field(min_length=1, max_length=30)


class BaselineSelection(Contract):
    module_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    repository: Literal[
        "https://github.com/marcor0311/aws-cloud-consultant-baseline-modules.git"
    ]
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    candidate_version: str = Field(min_length=1, max_length=50)
    approval_status: Literal["draft", "approved"]
    profile: str = Field(min_length=1, max_length=80)
    configuration: dict = Field(default_factory=dict)


class ArchitectureDecision(Contract):
    adr_id: str = Field(pattern=r"^ADR-[0-9]{3}$")
    title: str = Field(min_length=1, max_length=200)
    decision: str = Field(min_length=1, max_length=2000)
    alternatives: list[str] = Field(min_length=1, max_length=20)
    tradeoffs: list[str] = Field(min_length=1, max_length=20)


class IamPolicyStatement(Contract):
    sid: str = Field(pattern=r"^[A-Za-z0-9]+$")
    effect: Literal["Allow", "Deny"]
    actions: list[str] = Field(min_length=1, max_length=100)
    resources: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def iam_values_are_valid(self):
        if not all(
            re.fullmatch(r"[a-z0-9-]+:[A-Za-z0-9*?-]+", action)
            for action in self.actions
        ):
            raise ValueError("Cada acción IAM debe usar el formato servicio:acción.")
        if not all(resource == "*" or resource.startswith("arn:") for resource in self.resources):
            raise ValueError("Cada recurso IAM debe ser un ARN o '*'.")
        return self


class IamPolicyDocument(Contract):
    version: Literal["2012-10-17"] = "2012-10-17"
    statements: list[IamPolicyStatement] = Field(min_length=1, max_length=100)

    def aws_document(self) -> dict:
        return {
            "Version": self.version,
            "Statement": [
                {
                    "Sid": statement.sid,
                    "Effect": statement.effect,
                    "Action": sorted(statement.actions),
                    "Resource": sorted(statement.resources),
                }
                for statement in self.statements
            ],
        }


class SecurityControl(Contract):
    control_id: str = Field(pattern=r"^SEC-[0-9]{3}$")
    description: str = Field(min_length=1, max_length=1000)
    policy_as_code_path: str | None = Field(default=None, max_length=500)
    iam_policy: IamPolicyDocument | None = None


class CostAssumption(Contract):
    """Legacy 1.0 input retained for backwards-compatible package parsing."""

    resource_id: str
    metric: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(ge=0, max_digits=24, decimal_places=6)
    unit: str = Field(min_length=1, max_length=100)


class ArchitecturePackage(Contract):
    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,59}$")
    source_issue: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$"
    )
    region: str = Field(pattern=r"^[a-z]{2}(?:-[a-z]+)+-[0-9]$")
    environment: Literal["dev", "test", "stage", "prod"]
    requirements: list[Requirement] = Field(min_length=1, max_length=100)
    resources: list[ResourceDecision] = Field(min_length=1, max_length=100)
    baselines: list[BaselineSelection] = Field(default_factory=list, max_length=30)
    missing_baselines: list[str] = Field(default_factory=list, max_length=30)
    decisions: list[ArchitectureDecision] = Field(min_length=1, max_length=30)
    security_controls: list[SecurityControl] = Field(min_length=1, max_length=100)
    cost_assumptions: list[CostAssumption] = Field(min_length=1, max_length=100)
    economic_contract: EconomicContract | None = None
    topology: ArchitectureTopology | None = None
    diagram_mermaid: str | None = Field(default=None, max_length=20000)
    risks: list[str] = Field(min_length=1, max_length=50)
    open_questions: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def references_are_coherent(self):
        resource_ids = [resource.resource_id for resource in self.resources]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("Los identificadores de recursos no pueden repetirse.")
        known = set(resource_ids)
        for resource in self.resources:
            if resource.resource_id in resource.dependencies:
                raise ValueError("Un recurso no puede depender de sí mismo.")
            if not set(resource.dependencies) <= known:
                raise ValueError("Todas las dependencias deben referenciar recursos.")
        visiting = set()
        visited = set()
        dependencies = {
            resource.resource_id: set(resource.dependencies)
            for resource in self.resources
        }

        def visit(resource_id):
            if resource_id in visiting:
                raise ValueError("Las dependencias de despliegue no pueden ser cíclicas.")
            if resource_id in visited:
                return
            visiting.add(resource_id)
            for dependency in dependencies[resource_id]:
                visit(dependency)
            visiting.remove(resource_id)
            visited.add(resource_id)

        for resource_id in known:
            visit(resource_id)
        if self.schema_version in {"1.0", "1.1"} and not self.diagram_mermaid:
            raise ValueError("Los contratos anteriores requieren diagram_mermaid.")
        if self.schema_version == "1.2":
            if self.topology is None:
                raise ValueError("ArchitecturePackage 1.2 requiere topology.")
            topology_ids = {node.resource_id for node in self.topology.nodes}
            if topology_ids != known:
                raise ValueError("La topología debe representar exactamente los recursos.")
            dependency_edges = {
                (dependency, resource.resource_id)
                for resource in self.resources
                for dependency in resource.dependencies
            }
            topology_dependencies = {
                (relation.source, relation.target)
                for relation in self.topology.relations
                if relation.relation_type == "deployment_dependency"
            }
            if topology_dependencies != dependency_edges:
                raise ValueError(
                    "Las dependencias de despliegue deben coincidir con resources."
                )
            object.__setattr__(self, "diagram_mermaid", self.topology.mermaid())
            for control in self.security_controls:
                if bool(control.policy_as_code_path) != bool(control.iam_policy):
                    raise ValueError(
                        "Cada política debe declarar conjuntamente ruta y documento IAM."
                    )
                if control.policy_as_code_path:
                    path = control.policy_as_code_path
                    if (
                        not path.startswith("policies/")
                        or not path.endswith(".json")
                        or ".." in path.split("/")
                    ):
                        raise ValueError(
                            "Las políticas deben escribirse como policies/*.json."
                        )
        if not {item.resource_id for item in self.cost_assumptions} <= known:
            raise ValueError("Los supuestos de costo deben referenciar recursos.")
        if self.schema_version == "1.1" and self.economic_contract is None:
            raise ValueError("ArchitecturePackage 1.1 requiere economic_contract.")
        if self.economic_contract:
            pricing_ids = [
                item.resource_id for item in self.economic_contract.pricing_inputs
            ]
            if len(pricing_ids) != len(set(pricing_ids)):
                raise ValueError("Los pricing_inputs no pueden repetir recursos.")
            if set(pricing_ids) != known:
                raise ValueError(
                    "Cada recurso debe tener un pricing_input, incluso si su cantidad "
                    "todavía es desconocida."
                )
            service_by_resource = {
                item.resource_id: item.aws_service for item in self.resources
            }
            for item in self.economic_contract.pricing_inputs:
                if item.region != self.region:
                    raise ValueError("La región económica debe coincidir con arquitectura.")
                if item.aws_service != service_by_resource[item.resource_id]:
                    raise ValueError("El servicio económico debe coincidir con el recurso.")
            requirement_ids = {item.requirement_id for item in self.requirements}
            decision_ids = {item.adr_id for item in self.decisions}
            for pricing_input in self.economic_contract.pricing_inputs:
                for dimension in pricing_input.dimensions:
                    source = dimension.source
                    if (
                        source.source_type == "requirement"
                        and source.source_reference not in requirement_ids
                    ):
                        raise ValueError(
                            "La procedencia requirement debe referenciar un requisito."
                        )
                    if (
                        source.source_type == "architecture"
                        and source.source_reference not in decision_ids
                    ):
                        raise ValueError(
                            "La procedencia architecture debe referenciar un ADR."
                        )
            unknown = self.economic_contract.blocking_reasons(requirement_ids)
            invalid_references = [
                item for item in unknown if item.startswith("unknown_requirement:")
            ]
            if invalid_references:
                raise ValueError("Las dimensiones referencian requisitos desconocidos.")
        return self

    def finops_blocking_reasons(self) -> list[str]:
        if self.economic_contract is None:
            return ["economic_contract_missing"]
        if self.economic_contract.contract_version == "1.0":
            return ["economic_contract_upgrade_required"]
        requirement_ids = {item.requirement_id for item in self.requirements}
        return self.economic_contract.blocking_reasons(requirement_ids)

    def artifacts(self) -> dict[str, str]:
        requirements = "# Requisitos de arquitectura\n\n" + "\n".join(
            f"- **{item.requirement_id}** {item.description} — Fuente: {item.source}"
            for item in self.requirements
        )
        resources = (
            f"# Arquitectura AWS — {self.project_id}\n\n"
            f"- Región: `{self.region}`\n"
            f"- Ambiente: `{self.environment}`\n"
            f"- Issue: {self.source_issue}\n\n"
            "## Recursos propuestos\n\n"
            + "\n".join(
            f"- **{item.resource_id} / {item.aws_service}:** {item.purpose}"
            for item in self.resources
            )
            + "\n\n## Riesgos\n\n"
            + "\n".join(f"- {risk}" for risk in self.risks)
            + "\n\n## Preguntas abiertas\n\n"
            + ("\n".join(f"- {question}" for question in self.open_questions) or "- Ninguna")
        )
        adrs = "# Decisiones de arquitectura\n\n" + "\n\n".join(
            f"## {item.adr_id} — {item.title}\n\n{item.decision}\n\n"
            f"Alternativas: {'; '.join(item.alternatives)}\n\n"
            f"Trade-offs: {'; '.join(item.tradeoffs)}"
            for item in self.decisions
        )
        security = "# Seguridad y políticas\n\n" + "\n".join(
            f"- **{item.control_id}:** {item.description}"
            + (f" — `{item.policy_as_code_path}`" if item.policy_as_code_path else "")
            for item in self.security_controls
        )
        artifacts = {
            "requirements.md": requirements + "\n",
            "architecture.md": resources + "\n",
            "architecture.mmd": self.diagram_mermaid.rstrip() + "\n",
            "adrs.md": adrs + "\n",
            "security.md": security + "\n",
            "architecture-package.json": json.dumps(
                self.model_dump(mode="json"), ensure_ascii=False, indent=2
            )
            + "\n",
        }
        if self.economic_contract:
            artifacts["pricing-inputs.json"] = (
                json.dumps(
                    self.economic_contract.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
        if self.topology:
            artifacts["architecture.aws-dac.yaml"] = self.topology.awsdac_yaml()
            artifacts["resources.yaml"] = yaml.safe_dump(
                {
                    "schema_version": "1.0",
                    "region": self.region,
                    "environment": self.environment,
                    "resources": [
                        {
                            "resource_id": resource.resource_id,
                            "aws_service": resource.aws_service,
                            "aws_resource_type": next(
                                node.aws_resource_type
                                for node in self.topology.nodes
                                if node.resource_id == resource.resource_id
                            ),
                            "dependencies": sorted(resource.dependencies),
                        }
                        for resource in sorted(
                            self.resources, key=lambda item: item.resource_id
                        )
                    ],
                },
                sort_keys=False,
                allow_unicode=True,
            )
            artifacts["module-selection.yaml"] = yaml.safe_dump(
                {
                    "schema_version": "1.0",
                    "modules": [
                        baseline.model_dump(mode="json")
                        for baseline in sorted(
                            self.baselines, key=lambda item: item.module_id
                        )
                    ],
                    "missing_modules": sorted(self.missing_baselines),
                },
                sort_keys=False,
                allow_unicode=True,
            )
        for control in self.security_controls:
            if control.policy_as_code_path and control.iam_policy:
                artifacts[control.policy_as_code_path] = (
                    json.dumps(
                        control.iam_policy.aws_document(),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                )
        return artifacts


class ArchitectureFinOpsHandoff(Contract):
    contract_version: Literal["1.0"] = "1.0"
    target_stage: Literal[4] = 4
    handoff_status: Literal["ready", "blocked"]
    blocking_reasons: list[str] = Field(default_factory=list, max_length=200)
    revision: int = Field(ge=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_issue: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$"
    )
    architecture_schema_version: Literal["1.0", "1.1", "1.2"]
    architecture: ArchitecturePackage
    economic_contract: EconomicContract | None
    documents: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def status_matches_blockers(self):
        if self.source_issue != self.architecture.source_issue:
            raise ValueError("El handoff debe conservar el issue de origen.")
        if self.architecture_schema_version != self.architecture.schema_version:
            raise ValueError("El handoff debe conservar la versión de arquitectura.")
        if self.economic_contract != self.architecture.economic_contract:
            raise ValueError("El contrato económico debe coincidir con arquitectura.")
        expected = self.architecture.finops_blocking_reasons()
        if self.blocking_reasons != expected:
            raise ValueError("Los bloqueos deben derivarse del contrato económico.")
        if self.handoff_status == "ready" and self.blocking_reasons:
            raise ValueError("Un handoff listo no puede contener bloqueos.")
        if self.handoff_status == "blocked" and not self.blocking_reasons:
            raise ValueError("Un handoff bloqueado debe explicar la causa.")
        return self
