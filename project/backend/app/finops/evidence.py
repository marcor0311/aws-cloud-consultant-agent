"""Verified evidence imported from real AWS Pricing Calculator exports."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.finops.calculator import CalculatorPreparation
from app.finops.models import FinOpsModel


class EvidenceArtifact(FinOpsModel):
    artifact_type: Literal["export_json", "export_csv", "export_pdf", "screenshot"]
    path: str = Field(min_length=1, max_length=500)
    media_type: str = Field(min_length=1, max_length=100)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class VerifiedCalculatorParameter(FinOpsModel):
    dimension_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    calculator_parameter: str = Field(min_length=1, max_length=100)
    planned_quantity: Decimal = Field(ge=0, max_digits=24, decimal_places=6)
    unit: str = Field(min_length=1, max_length=100)
    attributes: dict[str, str] = Field(default_factory=dict, max_length=20)
    verified_display: str = Field(min_length=1, max_length=500)


class PricingCalculatorEvidence(FinOpsModel):
    contract_version: Literal["1.0"] = "1.0"
    execution_id: str = Field(pattern=r"^pricing-[0-9a-f]{64}$")
    case_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,59}$")
    architecture_revision: int = Field(ge=1)
    architecture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resource_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    service_type: Literal["s3"]
    aws_service: Literal["Amazon S3"]
    region: str = Field(pattern=r"^[a-z]{2}(?:-[a-z]+)+-[0-9]$")
    parameters: list[VerifiedCalculatorParameter] = Field(min_length=1, max_length=50)
    monthly_cost: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    currency: Literal["USD"] | None = None
    executed_at: datetime
    estimate_url: str | None = Field(
        default=None,
        pattern=r"^https://calculator\.aws/#/estimate\?id=[0-9a-f]+$",
    )
    artifacts: list[EvidenceArtifact] = Field(default_factory=list, max_length=20)
    unrepresentable_parameters: list[str] = Field(default_factory=list, max_length=50)
    status: Literal["verified", "partial", "unverified"]
    provenance: Literal["aws_pricing_calculator"] = "aws_pricing_calculator"
    automation: Literal["codex_iab_playwright"] = "codex_iab_playwright"

    @model_validator(mode="after")
    def verification_is_evidence_backed(self):
        if self.executed_at.tzinfo is None or self.executed_at.utcoffset() is None:
            raise ValueError("executed_at debe incluir zona horaria.")
        if self.status == "verified":
            if self.monthly_cost is None or self.currency is None:
                raise ValueError("Una ejecución verificada requiere costo y moneda.")
            if not self.estimate_url or not self.artifacts:
                raise ValueError("Una ejecución verificada requiere URL y artefactos.")
            if self.unrepresentable_parameters:
                raise ValueError("Una ejecución verificada no puede omitir parámetros.")
        if self.status != "verified" and not self.unrepresentable_parameters:
            raise ValueError("La evidencia incompleta debe explicar sus limitaciones.")
        expected = self.make_execution_id(
            self.architecture_sha256,
            self.resource_id,
            self.region,
            self.parameters,
        )
        if self.execution_id != expected:
            raise ValueError("execution_id no corresponde a la entrada verificada.")
        return self

    @staticmethod
    def make_execution_id(architecture_sha256, resource_id, region, parameters):
        canonical = json.dumps(
            {
                "architecture_sha256": architecture_sha256,
                "resource_id": resource_id,
                "region": region,
                "parameters": [
                    item.model_dump(mode="json")
                    if isinstance(item, VerifiedCalculatorParameter)
                    else item
                    for item in parameters
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return "pricing-" + hashlib.sha256(canonical.encode()).hexdigest()


class S3ExportEvidenceBuilder:
    """Validate the observed S3 export and fail loudly when its shape changes."""

    REGION_NAMES = {"us-east-1": "US East (N. Virginia)"}

    def build(
        self,
        preparation_payload,
        resource_id,
        export_payload,
        artifact,
        executed_at,
    ):
        preparation = CalculatorPreparation.model_validate(preparation_payload)
        artifact = EvidenceArtifact.model_validate(artifact)
        resource = next(
            (item for item in preparation.resources if item.resource_id == resource_id),
            None,
        )
        if resource is None or resource.service_type != "s3":
            raise ValueError("La preparación no contiene el recurso S3 solicitado.")
        if resource.status != "ready":
            raise ValueError("Solo una preparación S3 lista puede verificarse.")
        expected_region = self.REGION_NAMES.get(resource.region)
        if not expected_region:
            raise ValueError("La región todavía no fue validada contra la interfaz.")

        metadata = export_payload.get("Metadata", {})
        total = export_payload.get("Total Cost", {})
        services = export_payload.get("Groups", {}).get("Services", [])
        if metadata.get("Currency") != "USD" or "monthly" not in total:
            raise ValueError("Cambió la estructura monetaria de la exportación AWS.")
        if not services or any(item.get("Region") != expected_region for item in services):
            raise ValueError("La exportación AWS no conserva la región esperada.")

        properties = {
            key: value
            for service in services
            for key, value in service.get("Properties", {}).items()
        }
        verified = []
        missing = []
        for dimension in resource.dimensions:
            label, display = self._expected_property(dimension)
            actual = properties.get(label)
            if actual != display:
                missing.append(
                    f"ui_mismatch:{dimension.dimension_id}:{label}:"
                    f"expected={display}:actual={actual}"
                )
                continue
            verified.append(
                VerifiedCalculatorParameter(
                    dimension_id=dimension.dimension_id,
                    calculator_parameter=dimension.calculator_parameter,
                    planned_quantity=dimension.quantity,
                    unit=dimension.unit,
                    attributes=dimension.attributes,
                    verified_display=actual,
                )
            )
        status = "verified" if not missing else "partial"
        execution_id = PricingCalculatorEvidence.make_execution_id(
            preparation.architecture_sha256,
            resource.resource_id,
            resource.region,
            verified,
        )
        return PricingCalculatorEvidence(
            execution_id=execution_id,
            case_id=preparation.case_id,
            project_id=preparation.project_id,
            architecture_revision=preparation.architecture_revision,
            architecture_sha256=preparation.architecture_sha256,
            resource_id=resource.resource_id,
            service_type="s3",
            aws_service="Amazon S3",
            region=resource.region,
            parameters=verified,
            monthly_cost=Decimal(total["monthly"]),
            currency="USD",
            executed_at=executed_at,
            estimate_url=metadata.get("Share Url"),
            artifacts=[artifact],
            unrepresentable_parameters=missing,
            status=status,
        )

    @staticmethod
    def _expected_property(dimension):
        quantity = format(dimension.quantity, "f")
        if dimension.calculator_parameter == "monthly_storage":
            return "S3 Standard storage", f"{quantity} GB per month"
        if dimension.calculator_parameter == "monthly_requests":
            operation = dimension.attributes.get("operation")
            if operation == "GET":
                return (
                    "GET, SELECT, and all other requests from S3 Standard",
                    quantity,
                )
        if dimension.calculator_parameter == "monthly_data_transfer_out":
            if dimension.attributes.get("destination") == "internet":
                return "DT Outbound: Internet", f"{quantity} GB per month"
        raise ValueError(
            f"La dimensión {dimension.dimension_id} no tiene mapeo UI validado."
        )
