"""Price-free instructions for an external AWS Pricing Calculator operator."""

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.architecture.economics import AssumptionSource, S3PricingInput
from app.finops.models import FinOpsIntake, FinOpsModel


class CalculatorDimensionInstruction(FinOpsModel):
    dimension_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    metric: str = Field(min_length=1, max_length=100)
    status: Literal["ready", "blocked"]
    calculator_parameter: str | None = Field(default=None, min_length=1, max_length=100)
    quantity: Decimal | None = Field(
        default=None, ge=0, max_digits=24, decimal_places=6
    )
    unit: str = Field(min_length=1, max_length=100)
    period: Literal["month"] = "month"
    attributes: dict[str, str] = Field(default_factory=dict, max_length=20)
    source: AssumptionSource
    requirement_ids: list[str] = Field(default_factory=list, max_length=30)
    blocking_reason: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def readiness_is_explicit(self):
        if self.status == "ready":
            if self.quantity is None or not self.calculator_parameter:
                raise ValueError("Una instrucción lista requiere cantidad y parámetro.")
            if self.blocking_reason:
                raise ValueError("Una instrucción lista no puede estar bloqueada.")
        elif not self.blocking_reason:
            raise ValueError("Una instrucción bloqueada debe explicar la causa.")
        return self


class CalculatorResourceInstruction(FinOpsModel):
    resource_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    service_type: str = Field(min_length=1, max_length=80)
    aws_service: str = Field(min_length=1, max_length=120)
    service_code: str = Field(min_length=1, max_length=80)
    region: str = Field(pattern=r"^[a-z]{2}(?:-[a-z]+)+-[0-9]$")
    configuration: dict[str, str] = Field(default_factory=dict, max_length=20)
    status: Literal["ready", "blocked"]
    dimensions: list[CalculatorDimensionInstruction] = Field(
        min_length=1, max_length=50
    )

    @model_validator(mode="after")
    def status_matches_dimensions(self):
        blocked = any(item.status == "blocked" for item in self.dimensions)
        if (self.status == "blocked") != blocked:
            raise ValueError("El estado del recurso debe reflejar sus dimensiones.")
        return self


class CalculatorPreparation(FinOpsModel):
    contract_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,59}$")
    architecture_revision: int = Field(ge=1)
    architecture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_contract_version: Literal["1.1"] = "1.1"
    operator: Literal["codex-browser"] = "codex-browser"
    source: Literal["aws-pricing-calculator"] = "aws-pricing-calculator"
    status: Literal["ready", "partial", "blocked"]
    resources: list[CalculatorResourceInstruction] = Field(
        min_length=1, max_length=100
    )
    blocking_reasons: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def status_matches_resources(self):
        blocked_count = sum(item.status == "blocked" for item in self.resources)
        expected = (
            "ready"
            if blocked_count == 0
            else "blocked"
            if blocked_count == len(self.resources)
            else "partial"
        )
        if self.status != expected:
            raise ValueError("El estado global debe reflejar los recursos preparados.")
        derived = [
            item.blocking_reason
            for resource in self.resources
            for item in resource.dimensions
            if item.blocking_reason
        ]
        if self.blocking_reasons != derived:
            raise ValueError("Los bloqueos deben derivarse de las dimensiones.")
        return self


S3_PARAMETERS = {
    "storage": "monthly_storage",
    "requests": "monthly_requests",
    "data_retrieval": "monthly_data_retrieval",
    "data_transfer_out": "monthly_data_transfer_out",
    "lifecycle_transitions": "monthly_lifecycle_transitions",
}


class PricingCalculatorPreparer:
    """Build deterministic operator input without using prices or UI selectors."""

    def prepare(self, intake_payload):
        intake = FinOpsIntake.model_validate(intake_payload)
        contract = intake.handoff.economic_contract
        if contract is None or contract.contract_version != "1.1":
            raise ValueError("AWS Pricing Calculator requiere contrato económico 1.1.")

        resources = [self.prepare_resource(item) for item in contract.pricing_inputs]
        blockers = [
            dimension.blocking_reason
            for resource in resources
            for dimension in resource.dimensions
            if dimension.blocking_reason
        ]
        blocked_count = sum(resource.status == "blocked" for resource in resources)
        status = (
            "ready"
            if blocked_count == 0
            else "blocked"
            if blocked_count == len(resources)
            else "partial"
        )
        return CalculatorPreparation(
            case_id=intake.case_id,
            project_id=intake.project_id,
            architecture_revision=intake.handoff.revision,
            architecture_sha256=intake.handoff.artifact_sha256,
            status=status,
            resources=resources,
            blocking_reasons=blockers,
        )

    def prepare_resource(self, pricing_input):
        if isinstance(pricing_input, S3PricingInput):
            dimensions = [self._s3_dimension(item) for item in pricing_input.dimensions]
        else:
            dimensions = [
                self._unsupported_dimension(pricing_input.service_type, item)
                for item in pricing_input.dimensions
            ]
        return CalculatorResourceInstruction(
            resource_id=pricing_input.resource_id,
            service_type=pricing_input.service_type,
            aws_service=pricing_input.aws_service,
            service_code=pricing_input.service_code,
            region=pricing_input.region,
            configuration=self._resource_configuration(pricing_input),
            status=(
                "blocked"
                if any(item.status == "blocked" for item in dimensions)
                else "ready"
            ),
            dimensions=dimensions,
        )

    @staticmethod
    def _attributes(dimension):
        names = ("storage_class", "operation", "destination")
        return {
            name: value
            for name in names
            if (value := getattr(dimension, name, None)) is not None
        }

    @staticmethod
    def _resource_configuration(pricing_input):
        common = {
            "resource_id",
            "service_type",
            "aws_service",
            "service_code",
            "region",
            "dimensions",
        }
        return {
            name: str(value)
            for name, value in pricing_input.model_dump(mode="json").items()
            if name not in common and value is not None
        }

    @staticmethod
    def _unsupported_attributes(dimension):
        common = {
            "dimension_id",
            "metric",
            "quantity",
            "unit",
            "period",
            "source",
            "requirement_ids",
            "missing_reason",
        }
        return {
            name: str(value)
            for name, value in dimension.model_dump(mode="json").items()
            if name not in common and value is not None
        }

    def _s3_dimension(self, dimension):
        if dimension.quantity is None:
            return CalculatorDimensionInstruction(
                dimension_id=dimension.dimension_id,
                metric=dimension.metric,
                status="blocked",
                calculator_parameter=S3_PARAMETERS[dimension.metric],
                quantity=None,
                unit=dimension.unit,
                attributes=self._attributes(dimension),
                source=dimension.source,
                requirement_ids=dimension.requirement_ids,
                blocking_reason=(
                    f"missing_quantity:{dimension.dimension_id}:"
                    f"{dimension.missing_reason}"
                ),
            )
        return CalculatorDimensionInstruction(
            dimension_id=dimension.dimension_id,
            metric=dimension.metric,
            status="ready",
            calculator_parameter=S3_PARAMETERS[dimension.metric],
            quantity=dimension.quantity,
            unit=dimension.unit,
            attributes=self._attributes(dimension),
            source=dimension.source,
            requirement_ids=dimension.requirement_ids,
        )

    @staticmethod
    def _unsupported_dimension(service_type, dimension):
        return CalculatorDimensionInstruction(
            dimension_id=dimension.dimension_id,
            metric=dimension.metric,
            status="blocked",
            quantity=dimension.quantity,
            unit=dimension.unit,
            attributes=PricingCalculatorPreparer._unsupported_attributes(dimension),
            source=dimension.source,
            requirement_ids=dimension.requirement_ids,
            blocking_reason=(
                f"unsupported_dimension:{service_type}:"
                f"{dimension.dimension_id}:{dimension.metric}"
            ),
        )
