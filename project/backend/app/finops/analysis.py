"""Economic analysis derived only from approved inputs and verified evidence."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.finops.evidence import PricingCalculatorEvidence
from app.finops.models import FinOpsIntake, FinOpsModel

MONEY = Decimal("0.01")
PERCENT = Decimal("0.01")


def money(value):
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def percent(value):
    return value.quantize(PERCENT, rounding=ROUND_HALF_UP)


class BudgetReference(FinOpsModel):
    status: Literal["known", "unknown"]
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    period: Literal["month", "year"] | None = None
    source_reference: str = Field(min_length=1, max_length=500)
    approval_reference: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def values_match_status(self):
        values = (self.amount, self.currency, self.period)
        if self.status == "known" and any(value is None for value in values):
            raise ValueError("Un presupuesto conocido requiere monto, moneda y período.")
        if self.status == "unknown" and any(value is not None for value in values):
            raise ValueError("Un presupuesto desconocido no puede contener valores.")
        return self


class CostBreakdown(FinOpsModel):
    resource_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    aws_service: str = Field(min_length=1, max_length=120)
    monthly_cost: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    annual_cost: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    share_of_verified_subtotal_percent: Decimal = Field(
        ge=0, le=100, max_digits=7, decimal_places=2
    )
    evidence_id: str = Field(pattern=r"^pricing-[0-9a-f]{64}$")


class CoverageSummary(FinOpsModel):
    expected_resources: int = Field(ge=1)
    verified_resources: int = Field(ge=0)
    resource_coverage_percent: Decimal = Field(
        ge=0, le=100, max_digits=7, decimal_places=2
    )
    expected_dimensions: int = Field(ge=1)
    verified_dimensions: int = Field(ge=0)
    dimension_coverage_percent: Decimal = Field(
        ge=0, le=100, max_digits=7, decimal_places=2
    )
    pending_resources: list[str] = Field(default_factory=list, max_length=100)
    pending_dimensions: list[str] = Field(default_factory=list, max_length=500)
    excluded_costs: list[str] = Field(default_factory=list, max_length=100)
    complete: bool


class BudgetComparison(FinOpsModel):
    status: Literal[
        "comparable", "coverage_incomplete", "currency_mismatch", "budget_unknown"
    ]
    cost_currency: str = Field(pattern=r"^[A-Z]{3}$")
    budget: BudgetReference
    monthly_budget: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    annual_budget: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    monthly_variance: Decimal | None = Field(
        default=None, max_digits=18, decimal_places=6
    )
    annual_variance: Decimal | None = Field(
        default=None, max_digits=18, decimal_places=6
    )
    absolute_difference: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    difference_percent: Decimal | None = Field(
        default=None, max_digits=12, decimal_places=2
    )
    verified_subtotal_percent_of_budget: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    provisional: bool
    blocking_reasons: list[str] = Field(default_factory=list, max_length=20)


class ScenarioAnalysis(FinOpsModel):
    scenario: Literal["base", "higher_demand", "lower_demand", "optimized"]
    status: Literal["evaluated", "partial", "blocked"]
    monthly_cost: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    annual_cost: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=6
    )
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    blocking_reasons: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def status_matches_evidence(self):
        if self.status == "evaluated" and (
            self.monthly_cost is None or not self.evidence_ids or self.blocking_reasons
        ):
            raise ValueError("Un escenario evaluado requiere evidencia completa.")
        if self.status != "evaluated" and not self.blocking_reasons:
            raise ValueError("Un escenario incompleto debe explicar sus bloqueos.")
        return self


class OptimizationRecommendation(FinOpsModel):
    resource_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    recommendation: str = Field(min_length=1, max_length=1000)
    justification: str = Field(min_length=1, max_length=1000)
    financial_impact: Literal["not_quantified"] = "not_quantified"
    technical_risk: str = Field(min_length=1, max_length=1000)
    architecture_approval_required: Literal[True] = True


class FinOpsEconomicAnalysis(FinOpsModel):
    contract_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,59}$")
    architecture_revision: int = Field(ge=1)
    architecture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    operational_status: Literal["ready_for_decision", "partial", "blocked"]
    budget_result: Literal[
        "within_budget", "near_limit", "over_budget", "not_evaluable"
    ]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    verified_monthly_subtotal: Decimal = Field(
        ge=0, max_digits=18, decimal_places=6
    )
    verified_annual_subtotal: Decimal = Field(
        ge=0, max_digits=18, decimal_places=6
    )
    breakdown: list[CostBreakdown] = Field(default_factory=list, max_length=100)
    coverage: CoverageSummary
    budget_comparison: BudgetComparison
    scenarios: list[ScenarioAnalysis] = Field(min_length=4, max_length=4)
    recommendations: list[OptimizationRecommendation] = Field(
        default_factory=list, max_length=100
    )
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    decision_reference: None = None


class FinOpsEconomicAnalyzer:
    """Analyze verified subtotals without turning them into an approval decision."""

    def analyze(self, intake_payload, evidence_payloads, budget_reference=None):
        intake = FinOpsIntake.model_validate(intake_payload)
        evidences = [
            PricingCalculatorEvidence.model_validate(item) for item in evidence_payloads
        ]
        if not evidences:
            raise ValueError("El análisis requiere al menos una evidencia de precios.")
        self._validate_evidence_identity(intake, evidences)

        contract = intake.handoff.economic_contract
        if contract is None:
            raise ValueError("El handoff no contiene contrato económico.")
        expected = {item.resource_id: item for item in contract.pricing_inputs}
        if len({item.resource_id for item in evidences}) != len(evidences):
            raise ValueError("No se permiten evidencias duplicadas por recurso.")
        unknown = {item.resource_id for item in evidences} - set(expected)
        if unknown:
            raise ValueError("La evidencia contiene recursos ajenos al handoff.")

        verified = [item for item in evidences if item.status == "verified"]
        currencies = {item.currency for item in verified}
        if len(currencies) != 1 or None in currencies:
            raise ValueError("Los subtotales requieren una única moneda verificada.")
        currency = currencies.pop()
        monthly = money(sum((item.monthly_cost for item in verified), Decimal("0")))
        annual = money(monthly * Decimal("12"))
        breakdown = self._breakdown(verified, monthly)
        coverage = self._coverage(expected, verified)
        budget = (
            BudgetReference.model_validate(budget_reference)
            if budget_reference is not None
            else self._budget_from_handoff(contract.budget, intake.handoff.source_issue)
        )
        comparison = self.compare_budget(monthly, currency, budget, coverage.complete)
        budget_result = self._budget_result(comparison, monthly)
        evidence_ids = [item.execution_id for item in verified]
        scenarios = self._scenarios(monthly, annual, evidence_ids, coverage)
        recommendations = self._recommendations(expected, coverage)
        return FinOpsEconomicAnalysis(
            case_id=intake.case_id,
            project_id=intake.project_id,
            architecture_revision=intake.handoff.revision,
            architecture_sha256=intake.handoff.artifact_sha256,
            operational_status=("ready_for_decision" if coverage.complete else "partial"),
            budget_result=budget_result,
            currency=currency,
            verified_monthly_subtotal=monthly,
            verified_annual_subtotal=annual,
            breakdown=breakdown,
            coverage=coverage,
            budget_comparison=comparison,
            scenarios=scenarios,
            recommendations=recommendations,
            evidence_ids=evidence_ids,
        )

    @staticmethod
    def _validate_evidence_identity(intake, evidences):
        for evidence in evidences:
            if (
                evidence.case_id != intake.case_id
                or evidence.project_id != intake.project_id
                or evidence.architecture_revision != intake.handoff.revision
                or evidence.architecture_sha256 != intake.handoff.artifact_sha256
            ):
                raise ValueError("La evidencia no corresponde al handoff recibido.")

    @staticmethod
    def _budget_from_handoff(budget, approval_reference):
        source_reference = budget.source.source_reference or budget.source.notes
        return BudgetReference(
            status=budget.status,
            amount=budget.amount,
            currency=budget.currency,
            period=budget.period,
            source_reference=source_reference,
            approval_reference=approval_reference,
        )

    @staticmethod
    def _breakdown(evidences, monthly_subtotal):
        result = []
        for evidence in evidences:
            share = (
                Decimal("0")
                if monthly_subtotal == 0
                else percent(evidence.monthly_cost / monthly_subtotal * Decimal("100"))
            )
            result.append(
                CostBreakdown(
                    resource_id=evidence.resource_id,
                    aws_service=evidence.aws_service,
                    monthly_cost=money(evidence.monthly_cost),
                    annual_cost=money(evidence.monthly_cost * Decimal("12")),
                    share_of_verified_subtotal_percent=share,
                    evidence_id=evidence.execution_id,
                )
            )
        return result

    @staticmethod
    def _coverage(expected, verified):
        verified_by_resource = {item.resource_id: item for item in verified}
        pending_resources = sorted(set(expected) - set(verified_by_resource))
        expected_dimensions = {
            f"{resource_id}:{dimension.dimension_id}"
            for resource_id, pricing_input in expected.items()
            for dimension in pricing_input.dimensions
        }
        verified_dimensions = {
            f"{item.resource_id}:{parameter.dimension_id}"
            for item in verified
            for parameter in item.parameters
        }
        pending_dimensions = sorted(expected_dimensions - verified_dimensions)
        resource_count = len(expected)
        dimension_count = len(expected_dimensions)
        return CoverageSummary(
            expected_resources=resource_count,
            verified_resources=len(verified_by_resource),
            resource_coverage_percent=percent(
                Decimal(len(verified_by_resource)) / resource_count * Decimal("100")
            ),
            expected_dimensions=dimension_count,
            verified_dimensions=len(verified_dimensions),
            dimension_coverage_percent=percent(
                Decimal(len(verified_dimensions)) / dimension_count * Decimal("100")
            ),
            pending_resources=pending_resources,
            pending_dimensions=pending_dimensions,
            excluded_costs=[
                f"{item}: {expected[item].aws_service}" for item in pending_resources
            ],
            complete=not pending_resources and not pending_dimensions,
        )

    @staticmethod
    def compare_budget(monthly_cost, cost_currency, budget, coverage_complete):
        budget = BudgetReference.model_validate(budget)
        if budget.status == "unknown":
            return BudgetComparison(
                status="budget_unknown",
                cost_currency=cost_currency,
                budget=budget,
                provisional=True,
                blocking_reasons=["budget_unknown"],
            )
        if budget.currency != cost_currency:
            return BudgetComparison(
                status="currency_mismatch",
                cost_currency=cost_currency,
                budget=budget,
                provisional=True,
                blocking_reasons=[
                    f"currency_mismatch:{cost_currency}:{budget.currency}",
                    "authorized_dated_exchange_rate_required",
                ],
            )
        monthly_budget = money(
            budget.amount
            if budget.period == "month"
            else budget.amount / Decimal("12")
        )
        difference = money(monthly_budget - monthly_cost)
        spent_percent = (
            None
            if monthly_budget == 0
            else percent(monthly_cost / monthly_budget * Decimal("100"))
        )
        difference_percent = (
            None
            if monthly_budget == 0
            else percent(abs(difference) / monthly_budget * Decimal("100"))
        )
        return BudgetComparison(
            status="comparable" if coverage_complete else "coverage_incomplete",
            cost_currency=cost_currency,
            budget=budget,
            monthly_budget=monthly_budget,
            annual_budget=money(monthly_budget * Decimal("12")),
            monthly_variance=difference,
            annual_variance=money(difference * Decimal("12")),
            absolute_difference=abs(difference),
            difference_percent=difference_percent,
            verified_subtotal_percent_of_budget=spent_percent,
            provisional=not coverage_complete,
            blocking_reasons=([] if coverage_complete else ["cost_coverage_incomplete"]),
        )

    @staticmethod
    def _budget_result(comparison, monthly_cost):
        if comparison.status != "comparable":
            return "not_evaluable"
        return (
            "within_budget"
            if monthly_cost <= comparison.monthly_budget
            else "over_budget"
        )

    @staticmethod
    def _scenarios(monthly, annual, evidence_ids, coverage):
        base_status = "evaluated" if coverage.complete else "partial"
        base_reasons = [] if coverage.complete else ["cost_coverage_incomplete"]
        scenarios = [
            ScenarioAnalysis(
                scenario="base",
                status=base_status,
                monthly_cost=monthly,
                annual_cost=annual,
                evidence_ids=evidence_ids,
                blocking_reasons=base_reasons,
            )
        ]
        for name in ("higher_demand", "lower_demand", "optimized"):
            scenarios.append(
                ScenarioAnalysis(
                    scenario=name,
                    status="blocked",
                    blocking_reasons=[
                        "scenario_inputs_missing",
                        "verified_aws_pricing_calculator_estimate_required",
                    ],
                )
            )
        return scenarios

    @staticmethod
    def _recommendations(expected, coverage):
        recommendations = []
        for resource_id, pricing_input in expected.items():
            if pricing_input.service_type != "s3":
                continue
            recommendations.append(
                OptimizationRecommendation(
                    resource_id=resource_id,
                    recommendation=(
                        "Evaluar clases de almacenamiento o reglas de ciclo de vida "
                        "solo cuando exista evidencia del patrón de acceso."
                    ),
                    justification=(
                        "La estimación verificada usa S3 Standard; el handoff no "
                        "demuestra todavía que otra clase sea adecuada."
                    ),
                    technical_risk=(
                        "Una clase incorrecta puede aumentar recuperación, latencia "
                        "o transiciones. Requiere nueva estimación y aprobación."
                    ),
                )
            )
        return recommendations
