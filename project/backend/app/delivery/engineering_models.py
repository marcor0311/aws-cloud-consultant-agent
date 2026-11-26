"""Recorded engineering inputs and evidence, separate from the S3 demo contract."""

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.delivery.models import Contract, Money, Text

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Commit = Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
Repository = Annotated[str, Field(pattern=r"^[\w.-]+/[\w.-]+$")]
Reference = Annotated[str, Field(pattern=r"^https://[^\s@]+$", max_length=2000)]

CHECKS = (
    "terraform fmt",
    "terraform init",
    "terraform validate",
    "Trivy",
    "AWS Emulator TLS",
    "terraform plan",
    "Políticas del plan",
    "terraform apply",
    "Verificación después de apply",
    "terraform destroy",
    "Eliminar contenedor",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


class EngineeringFile(Contract):
    role: Literal[
        "requirements",
        "design",
        "policies",
        "calculator_export",
        "cost_workbook",
        "implementation",
        "log",
        "security_report",
        "policy_report",
    ]
    path: Text
    sha256: Digest
    reference: Reference


def package_digest(files):
    """Public manifest algorithm: binds roles, file names, hashes and source URLs."""
    return digest(
        sorted(
            [f.model_dump(mode="json") for f in files],
            key=lambda f: (f["role"], f["path"]),
        )
    )


class RecordedApproval(Contract):
    event_id: Text
    actor: Text
    reference: Reference


class UpstreamPackage(Contract):
    commit: Commit
    revision: int = Field(ge=1)
    files: list[EngineeringFile] = Field(min_length=2, max_length=3)
    approval: RecordedApproval


class PinnedModule(Contract):
    repository: Repository
    path: str = Field(pattern=r"^[\w-]+(?:/[\w-]+)*$")
    commit: Commit
    approval_reference: Reference
    approved_by: Text


class EngineeringIntake(Contract):
    schema_version: Literal["1.0"] = "1.0"
    intake_id: UUID
    case_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,119}$")
    incoming_handoff_id: Text
    repository: Repository
    architecture: UpstreamPackage
    finops: UpstreamPackage
    finops_architecture_commit: Commit
    finops_architecture_sha256: Digest
    modules: list[PinnedModule] = Field(min_length=1, max_length=30)
    region: str = Field(pattern=r"^[a-z]{2}(?:-[a-z]+)+-\d$")
    budget: Money
    estimate: Money
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    period: Literal["month", "year"]
    calculator_url: Annotated[
        str, Field(pattern=r"^https://calculator\.aws/[^\s]*$", max_length=2000)
    ]

    @model_validator(mode="after")
    def coherent(self):
        for package, roles in (
            (self.architecture, {"requirements", "design", "policies"}),
            (self.finops, {"calculator_export", "cost_workbook"}),
        ):
            if (
                len(package.files) != len(roles)
                or {f.role for f in package.files} != roles
            ):
                raise ValueError(
                    "El paquete requiere los archivos de arquitectura o FinOps completos y distintos"
                )
            prefix = f"https://github.com/{self.repository}/blob/{package.commit}/"
            if any(not f.reference.startswith(prefix) for f in package.files):
                raise ValueError(
                    "Los archivos deben referenciar el repositorio y commit exactos del paquete"
                )
        if self.finops_architecture_commit != self.architecture.commit:
            raise ValueError("FinOps corresponde a otro commit de arquitectura")
        if self.estimate > self.budget:
            raise ValueError(
                "La estimación excede el presupuesto del mismo periodo y moneda"
            )
        if len({(m.repository, m.path) for m in self.modules}) != len(self.modules):
            raise ValueError("Un módulo está repetido")
        files = [*self.architecture.files, *self.finops.files]
        if len({f.path for f in files}) != len(files):
            raise ValueError("Los archivos de entrada deben ser distintos")
        return self

    def approval_digest(self, stage):
        if stage == 3:
            value = {
                "package": self.architecture.model_dump(
                    mode="json", exclude={"approval"}
                ),
                "modules": [m.model_dump(mode="json") for m in self.modules],
                "region": self.region,
            }
        else:
            value = {
                "package": self.finops.model_dump(mode="json", exclude={"approval"}),
                **self.model_dump(
                    mode="json",
                    include={
                        "finops_architecture_commit",
                        "finops_architecture_sha256",
                        "budget",
                        "estimate",
                        "currency",
                        "period",
                        "calculator_url",
                    },
                ),
            }
        return digest({"repository": self.repository, **value})


class TechnicalCheck(Contract):
    name: Text
    status: Literal["passed", "failed", "not_run"]
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    kind: Literal["work", "rework"] = "work"
    failure_origin: (
        Literal[
            "terraform", "security", "policy", "connectivity", "cleanup", "undetermined"
        ]
        | None
    ) = None
    detail: Text

    @model_validator(mode="after")
    def measured(self):
        if self.name not in CHECKS:
            raise ValueError("Comprobación técnica desconocida")
        if self.status == "not_run":
            if self.started_at is not None or self.ended_at is not None:
                raise ValueError("Una comprobación no ejecutada no tiene intervalo")
        elif (
            self.started_at is None
            or self.ended_at is None
            or self.ended_at < self.started_at
        ):
            raise ValueError("Una comprobación ejecutada requiere un intervalo válido")
        if (self.status == "failed") != (self.failure_origin is not None):
            raise ValueError("Solo un fallo debe indicar su origen, o undetermined")
        return self


class EngineeringEvidence(Contract):
    schema_version: Literal["1.0"] = "1.0"
    scope: Literal["local_emulator"]
    run_id: UUID
    intake_id: UUID
    input_sha256: Digest
    implementation_commit: Commit
    implementation_tree_sha256: Digest
    plan_sha256: Digest | None = None
    run_reference: Reference
    modules: list[PinnedModule] = Field(min_length=1, max_length=30)
    versions: dict[str, Text]
    resources: list[Text] = Field(min_length=1, max_length=100)
    actor: Text
    checks: list[TechnicalCheck] = Field(min_length=11, max_length=11)
    files: list[EngineeringFile] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def complete(self):
        if {c.name for c in self.checks} != set(CHECKS):
            raise ValueError(
                "Registrar todas las comprobaciones, incluidas las no ejecutadas"
            )
        if (
            not {"terraform", "aws_provider", "aws_emulator", "trivy"}
            <= self.versions.keys()
        ):
            raise ValueError("Faltan versiones de las herramientas")
        if any(
            f.role not in {"implementation", "log", "security_report", "policy_report"}
            for f in self.files
        ):
            raise ValueError(
                "La evidencia solo admite implementación y resultados técnicos"
            )
        code = [f for f in self.files if f.role == "implementation"]
        if not code or package_digest(code) != self.implementation_tree_sha256:
            raise ValueError(
                "El manifiesto de implementación no coincide con sus archivos"
            )
        prefix = f"/blob/{self.implementation_commit}/"
        if any(prefix not in f.reference for f in code):
            raise ValueError("La implementación no referencia el commit probado")
        if (
            any(
                c.name == "terraform plan" and c.status == "passed" for c in self.checks
            )
            and not self.plan_sha256
        ):
            raise ValueError(
                "El plan ejecutado requiere su hash, sin adjuntar el plan ni el estado"
            )
        if len({f.path for f in self.files}) != len(self.files):
            raise ValueError("Archivo de evidencia repetido")
        if all(c.status == "passed" for c in self.checks) and not {
            "log",
            "security_report",
            "policy_report",
        } <= {f.role for f in self.files}:
            raise ValueError(
                "Una corrida exitosa requiere logs y respaldos de seguridad y políticas"
            )
        return self
