"""Versioned, price-free usage contract from Architecture to FinOps."""

from decimal import Decimal
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EconomicContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AssumptionSource(EconomicContractModel):
    source_type: Literal["requirement", "client", "architecture", "unknown"]
    source_reference: str | None = Field(default=None, min_length=1, max_length=500)
    notes: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def reference_matches_source(self):
        if self.source_type == "unknown" and not self.notes:
            raise ValueError("Una procedencia desconocida debe explicar qué falta.")
        if self.source_type != "unknown" and not self.source_reference:
            raise ValueError("La procedencia debe incluir source_reference.")
        return self


class Budget(EconomicContractModel):
    status: Literal["known", "unknown"]
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    currency: Literal["USD"] | None = None
    period: Literal["month", "year"] | None = None
    source: AssumptionSource

    @model_validator(mode="after")
    def values_match_status(self):
        values = (self.amount, self.currency, self.period)
        if self.status == "known" and any(value is None for value in values):
            raise ValueError(
                "Un presupuesto conocido requiere monto, moneda y periodo."
            )
        if self.status == "unknown" and any(value is not None for value in values):
            raise ValueError("Un presupuesto desconocido no puede inventar valores.")
        return self


class UsageDimension(EconomicContractModel):
    dimension_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    quantity: Decimal | None = Field(
        default=None, ge=0, max_digits=24, decimal_places=6
    )
    period: Literal["month"] = "month"
    source: AssumptionSource
    requirement_ids: list[str] = Field(default_factory=list, max_length=30)
    missing_reason: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def quantity_or_missing_reason(self):
        if self.quantity is None and not self.missing_reason:
            raise ValueError("Una cantidad desconocida requiere missing_reason.")
        if self.quantity is not None and self.missing_reason:
            raise ValueError("Una cantidad conocida no debe incluir missing_reason.")
        return self


class S3UsageDimension(UsageDimension):
    metric: Literal[
        "storage",
        "requests",
        "data_retrieval",
        "data_transfer_out",
        "lifecycle_transitions",
    ]
    unit: Literal["GB-month", "requests/month", "GB/month"]
    storage_class: (
        Literal[
            "STANDARD",
            "INTELLIGENT_TIERING",
            "STANDARD_IA",
            "ONEZONE_IA",
            "GLACIER_INSTANT_RETRIEVAL",
            "GLACIER_FLEXIBLE_RETRIEVAL",
            "DEEP_ARCHIVE",
        ]
        | None
    ) = None
    operation: Literal["GET", "SELECT", "PUT", "COPY", "POST", "LIST"] | None = None
    destination: Literal["internet", "same_region", "cross_region"] | None = None

    @model_validator(mode="after")
    def attributes_match_metric(self):
        expected_units = {
            "storage": "GB-month",
            "requests": "requests/month",
            "data_retrieval": "GB/month",
            "data_transfer_out": "GB/month",
            "lifecycle_transitions": "requests/month",
        }
        if self.unit != expected_units[self.metric]:
            raise ValueError("La unidad S3 no corresponde a la métrica.")
        needs_class = {"storage", "data_retrieval", "lifecycle_transitions"}
        if self.metric in needs_class and self.storage_class is None:
            raise ValueError("La dimensión S3 requiere storage_class.")
        if self.metric not in needs_class and self.storage_class is not None:
            raise ValueError("storage_class no aplica a esta dimensión S3.")
        if self.metric == "requests" and self.operation is None:
            raise ValueError("Las solicitudes S3 requieren operation.")
        if self.metric != "requests" and self.operation is not None:
            raise ValueError("operation solo aplica a solicitudes S3.")
        if self.metric == "data_transfer_out" and self.destination is None:
            raise ValueError("La transferencia S3 requiere destination.")
        if self.metric != "data_transfer_out" and self.destination is not None:
            raise ValueError("destination solo aplica a transferencia S3.")
        return self


class DynamoDBUsageDimension(UsageDimension):
    metric: Literal[
        "read_requests",
        "write_requests",
        "provisioned_read_capacity",
        "provisioned_write_capacity",
        "table_storage",
        "pitr_storage",
        "on_demand_backup_storage",
        "data_transfer_out",
    ]
    unit: Literal[
        "operations/month",
        "RCU-hours/month",
        "WCU-hours/month",
        "GB-month",
        "GB/month",
    ]
    average_item_size_kb: Decimal | None = Field(default=None, gt=0)
    read_consistency: Literal["eventual", "strong", "transactional"] | None = None
    table_class: Literal["STANDARD", "STANDARD_IA"] | None = None
    destination: Literal["internet", "same_region", "cross_region"] | None = None

    @model_validator(mode="after")
    def attributes_match_metric(self):
        expected_units = {
            "read_requests": "operations/month",
            "write_requests": "operations/month",
            "provisioned_read_capacity": "RCU-hours/month",
            "provisioned_write_capacity": "WCU-hours/month",
            "table_storage": "GB-month",
            "pitr_storage": "GB-month",
            "on_demand_backup_storage": "GB-month",
            "data_transfer_out": "GB/month",
        }
        if self.unit != expected_units[self.metric]:
            raise ValueError("La unidad DynamoDB no corresponde a la métrica.")
        request_metric = self.metric in {"read_requests", "write_requests"}
        if request_metric and self.average_item_size_kb is None:
            raise ValueError("Las operaciones DynamoDB requieren tamaño promedio.")
        if not request_metric and self.average_item_size_kb is not None:
            raise ValueError("El tamaño de elemento solo aplica a operaciones.")
        if self.metric == "read_requests" and self.read_consistency is None:
            raise ValueError("Las lecturas requieren su consistencia.")
        if self.metric != "read_requests" and self.read_consistency is not None:
            raise ValueError("read_consistency solo aplica a lecturas.")
        if self.metric == "table_storage" and self.table_class is None:
            raise ValueError("El almacenamiento requiere table_class.")
        if self.metric != "table_storage" and self.table_class is not None:
            raise ValueError("table_class solo aplica al almacenamiento de tabla.")
        if self.metric == "data_transfer_out" and self.destination is None:
            raise ValueError("La transferencia requiere destination.")
        if self.metric != "data_transfer_out" and self.destination is not None:
            raise ValueError("destination solo aplica a transferencia.")
        return self


class ApiGatewayUsageDimension(UsageDimension):
    metric: Literal["api_requests", "data_transfer_out"]
    unit: Literal["requests/month", "GB/month"]
    destination: Literal["internet", "same_region", "cross_region"] | None = None

    @model_validator(mode="after")
    def attributes_match_metric(self):
        expected = {"api_requests": "requests/month", "data_transfer_out": "GB/month"}
        if self.unit != expected[self.metric]:
            raise ValueError("La unidad API Gateway no corresponde a la métrica.")
        if self.metric == "data_transfer_out" and self.destination is None:
            raise ValueError("La transferencia requiere destination.")
        if self.metric != "data_transfer_out" and self.destination is not None:
            raise ValueError("destination solo aplica a transferencia.")
        return self


class LambdaUsageDimension(UsageDimension):
    metric: Literal["invocations", "compute_duration"]
    unit: Literal["requests/month", "milliseconds/month"]
    memory_mb: int | None = Field(default=None, ge=128, le=10240)
    architecture: Literal["x86_64", "arm64"] | None = None

    @model_validator(mode="after")
    def attributes_match_metric(self):
        expected = {
            "invocations": "requests/month",
            "compute_duration": "milliseconds/month",
        }
        if self.unit != expected[self.metric]:
            raise ValueError("La unidad Lambda no corresponde a la métrica.")
        if self.metric == "compute_duration":
            if self.memory_mb is None or self.architecture is None:
                raise ValueError("La duración Lambda requiere memoria y arquitectura.")
        elif self.memory_mb is not None or self.architecture is not None:
            raise ValueError("Memoria y arquitectura solo aplican a duración Lambda.")
        return self


class KmsUsageDimension(UsageDimension):
    metric: Literal["customer_managed_keys", "api_requests"]
    unit: Literal["keys/month", "requests/month"]
    operation_group: Literal["symmetric", "asymmetric", "key_agreement"] | None = None

    @model_validator(mode="after")
    def attributes_match_metric(self):
        expected = {
            "customer_managed_keys": "keys/month",
            "api_requests": "requests/month",
        }
        if self.unit != expected[self.metric]:
            raise ValueError("La unidad KMS no corresponde a la métrica.")
        if self.metric == "api_requests" and self.operation_group is None:
            raise ValueError("Las solicitudes KMS requieren operation_group.")
        if self.metric != "api_requests" and self.operation_group is not None:
            raise ValueError("operation_group solo aplica a solicitudes KMS.")
        return self


class CloudWatchLogsUsageDimension(UsageDimension):
    metric: Literal["log_ingestion", "archive_storage", "insights_scan"]
    unit: Literal["GB/month", "GB-month"]
    log_class: Literal["STANDARD", "INFREQUENT_ACCESS", "DELIVERY"]

    @model_validator(mode="after")
    def attributes_match_metric(self):
        expected = {
            "log_ingestion": "GB/month",
            "archive_storage": "GB-month",
            "insights_scan": "GB/month",
        }
        if self.unit != expected[self.metric]:
            raise ValueError("La unidad CloudWatch Logs no corresponde a la métrica.")
        return self


class PricingInputBase(EconomicContractModel):
    resource_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    region: str = Field(pattern=r"^[a-z]{2}(?:-[a-z]+)+-[0-9]$")

    def dimensions_list(self) -> list[UsageDimension]:
        return list(self.dimensions)

    @model_validator(mode="after")
    def dimensions_are_unique(self):
        identifiers = [item.dimension_id for item in self.dimensions]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Las dimensiones de consumo no pueden repetirse.")
        return self


class S3PricingInput(PricingInputBase):
    service_type: Literal["s3"]
    aws_service: Literal["Amazon S3"]
    service_code: Literal["AmazonS3"]
    dimensions: list[S3UsageDimension] = Field(min_length=1, max_length=50)


class DynamoDBPricingInput(PricingInputBase):
    service_type: Literal["dynamodb"]
    aws_service: Literal["Amazon DynamoDB"]
    service_code: Literal["AmazonDynamoDB"]
    billing_mode: Literal["PAY_PER_REQUEST", "PROVISIONED"]
    dimensions: list[DynamoDBUsageDimension] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def dimensions_match_billing_mode(self):
        metrics = {item.metric for item in self.dimensions}
        provisioned = {"provisioned_read_capacity", "provisioned_write_capacity"}
        on_demand = {"read_requests", "write_requests"}
        if self.billing_mode == "PROVISIONED" and metrics & on_demand:
            raise ValueError("PROVISIONED no acepta dimensiones on-demand.")
        if self.billing_mode == "PAY_PER_REQUEST" and metrics & provisioned:
            raise ValueError("PAY_PER_REQUEST no acepta capacidad aprovisionada.")
        return self


class ApiGatewayPricingInput(PricingInputBase):
    service_type: Literal["api_gateway"]
    aws_service: Literal["Amazon API Gateway"]
    service_code: Literal["AmazonApiGateway"]
    api_type: Literal["HTTP", "REST", "WEBSOCKET"]
    dimensions: list[ApiGatewayUsageDimension] = Field(min_length=1, max_length=50)


class LambdaPricingInput(PricingInputBase):
    service_type: Literal["lambda"]
    aws_service: Literal["AWS Lambda"]
    service_code: Literal["AWSLambda"]
    dimensions: list[LambdaUsageDimension] = Field(min_length=1, max_length=50)


class KmsPricingInput(PricingInputBase):
    service_type: Literal["kms"]
    aws_service: Literal["AWS KMS"]
    service_code: Literal["awskms"]
    dimensions: list[KmsUsageDimension] = Field(min_length=1, max_length=50)


class CloudWatchLogsPricingInput(PricingInputBase):
    service_type: Literal["cloudwatch_logs"]
    aws_service: Literal["Amazon CloudWatch Logs"]
    service_code: Literal["AmazonCloudWatch"]
    dimensions: list[CloudWatchLogsUsageDimension] = Field(min_length=1, max_length=50)


PricingInputV1_1 = Annotated[
    Union[
        S3PricingInput,
        DynamoDBPricingInput,
        ApiGatewayPricingInput,
        LambdaPricingInput,
        KmsPricingInput,
        CloudWatchLogsPricingInput,
    ],
    Field(discriminator="service_type"),
]


class LegacyConsumptionDimension(UsageDimension):
    metric: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=100)
    pricing_attributes: dict[str, str] = Field(default_factory=dict, max_length=30)


class LegacyPricingInput(PricingInputBase):
    aws_service: str = Field(min_length=1, max_length=120)
    service_code: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9-]{1,79}$")
    dimensions: list[LegacyConsumptionDimension] = Field(min_length=1, max_length=50)


class EconomicContractBase(EconomicContractModel):
    budget: Budget

    def blocking_reasons(self, requirement_ids: set[str]) -> list[str]:
        reasons: list[str] = []
        if self.budget.status == "unknown":
            reasons.append("budget_unknown")
        if self.budget.source.source_type == "unknown":
            reasons.append("budget_source_unknown")
        for pricing_input in self.pricing_inputs:
            for dimension in pricing_input.dimensions_list():
                prefix = f"{pricing_input.resource_id}:{dimension.dimension_id}"
                if dimension.quantity is None:
                    reasons.append(f"quantity_unknown:{prefix}")
                if dimension.source.source_type == "unknown":
                    reasons.append(f"source_unknown:{prefix}")
                for requirement_id in dimension.requirement_ids:
                    if requirement_id not in requirement_ids:
                        reasons.append(f"unknown_requirement:{prefix}:{requirement_id}")
        return reasons


class EconomicContractV1(EconomicContractBase):
    contract_version: Literal["1.0"]
    pricing_inputs: list[LegacyPricingInput] = Field(min_length=1, max_length=100)


class EconomicContractV1_1(EconomicContractBase):
    contract_version: Literal["1.1"]
    pricing_inputs: list[PricingInputV1_1] = Field(min_length=1, max_length=100)


EconomicContract = Annotated[
    Union[EconomicContractV1, EconomicContractV1_1],
    Field(discriminator="contract_version"),
]
