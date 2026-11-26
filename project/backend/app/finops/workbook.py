"""Deterministic FinOps forecast workbook derived from persisted evidence."""

import hashlib
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties
from pydantic import Field

from app.finops.analysis import FinOpsEconomicAnalysis
from app.finops.evidence import PricingCalculatorEvidence
from app.finops.models import FinOpsIntake, FinOpsModel


class ForecastWorkbookArtifact(FinOpsModel):
    contract_version: str = "1.0"
    generator_version: str = "1.0"
    status: str = Field(pattern=r"^(generated|partial)$")
    case_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,59}$")
    architecture_revision: int = Field(ge=1)
    architecture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    relative_path: str = Field(
        pattern=r"^docs/04-finops/versions/v[0-9]{3}/forecast\.xlsx$"
    )
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_ids: list[str]
    pending_resources: list[str]
    idempotency_key: str = Field(pattern=r"^finops-workbook:[^:]+:[0-9]+:[0-9a-f]{64}$")


class ForecastWorkbookGenerator:
    """Create one readable workbook without inventing missing prices or scenarios."""

    SHEETS = [
        "Resumen",
        "Costos",
        "Proyección",
        "Escenarios",
        "Evidencias",
        "Supuestos",
    ]
    HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
    SECTION_FILL = PatternFill("solid", fgColor="D9EAF7")
    PENDING_FILL = PatternFill("solid", fgColor="FFF2CC")

    def generate(self, output_root, intake_payload, analysis_payload, evidences):
        intake = FinOpsIntake.model_validate(intake_payload)
        analysis = FinOpsEconomicAnalysis.model_validate(analysis_payload)
        evidence = [
            PricingCalculatorEvidence.model_validate(item) for item in evidences
        ]
        self._validate_identity(intake, analysis, evidence)

        relative = (
            f"docs/04-finops/versions/v{intake.handoff.revision:03d}/forecast.xlsx"
        )
        target = Path(output_root) / relative
        target.parent.mkdir(parents=True, exist_ok=True)

        workbook = Workbook()
        workbook.calculation = CalcProperties(
            calcMode="auto", fullCalcOnLoad=True, forceFullCalc=True
        )
        workbook.remove(workbook.active)
        for name in self.SHEETS:
            workbook.create_sheet(name)
        self._summary(workbook["Resumen"], intake, analysis)
        cost_rows = self._costs(workbook["Costos"], intake, analysis)
        self._projection(workbook["Proyección"], cost_rows)
        self._scenarios(workbook["Escenarios"], analysis)
        self._evidence(workbook["Evidencias"], evidence)
        self._assumptions(workbook["Supuestos"], intake)
        self._finish(workbook)
        workbook.save(target)

        reopened = load_workbook(target, data_only=False)
        if reopened.sheetnames != self.SHEETS:
            raise ValueError("forecast.xlsx no conserva las pestañas requeridas.")
        reopened.close()
        file_sha = hashlib.sha256(target.read_bytes()).hexdigest()
        source_digest = self.source_digest(intake, analysis, evidence)
        return ForecastWorkbookArtifact(
            status="generated" if analysis.coverage.complete else "partial",
            case_id=intake.case_id,
            project_id=intake.project_id,
            architecture_revision=intake.handoff.revision,
            architecture_sha256=intake.handoff.artifact_sha256,
            relative_path=relative,
            file_sha256=file_sha,
            source_digest=source_digest,
            evidence_ids=sorted(item.execution_id for item in evidence),
            pending_resources=analysis.coverage.pending_resources,
            idempotency_key=(
                f"finops-workbook:{intake.case_id}:{intake.handoff.revision}:"
                f"{source_digest}"
            ),
        )

    @staticmethod
    def source_digest(intake, analysis, evidence):
        payload = "|".join(
            [
                intake.handoff.artifact_sha256,
                analysis.model_dump_json(),
                *sorted(item.model_dump_json() for item in evidence),
            ]
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _validate_identity(intake, analysis, evidence):
        expected = (
            intake.case_id,
            intake.project_id,
            intake.handoff.revision,
            intake.handoff.artifact_sha256,
        )
        actual = (
            analysis.case_id,
            analysis.project_id,
            analysis.architecture_revision,
            analysis.architecture_sha256,
        )
        if actual != expected:
            raise ValueError("El análisis no corresponde al handoff FinOps.")
        for item in evidence:
            if (
                item.case_id,
                item.project_id,
                item.architecture_revision,
                item.architecture_sha256,
            ) != expected:
                raise ValueError("La evidencia no corresponde al handoff FinOps.")

    def _summary(self, sheet, intake, analysis):
        sheet.append(["Forecast de costos AWS", intake.project_id])
        sheet.append(["Expediente", intake.case_id])
        sheet.append(["Revisión de Arquitectura", intake.handoff.revision])
        sheet.append(["SHA-256 de Arquitectura", intake.handoff.artifact_sha256])
        sheet.append(["Estado", analysis.operational_status])
        sheet.append(["Resultado presupuestario", analysis.budget_result])
        sheet.append(["Moneda", analysis.currency])
        sheet.append(
            [
                "Costo mensual verificado",
                "=Costos!D{}".format(len(intake.handoff.architecture.resources) + 2),
            ]
        )
        sheet.append(
            [
                "Costo anual verificado",
                "=Costos!E{}".format(len(intake.handoff.architecture.resources) + 2),
            ]
        )
        sheet.append(
            [
                "Cobertura de recursos",
                float(analysis.coverage.resource_coverage_percent) / 100,
            ]
        )
        sheet.append(
            [
                "Cobertura de dimensiones",
                float(analysis.coverage.dimension_coverage_percent) / 100,
            ]
        )
        comparison = analysis.budget_comparison
        sheet.append(
            [
                "Presupuesto mensual",
                float(comparison.monthly_budget)
                if comparison.monthly_budget is not None
                else None,
            ]
        )
        sheet.append(
            [
                "Diferencia mensual",
                float(comparison.monthly_variance)
                if comparison.monthly_variance is not None
                else None,
            ]
        )
        sheet.append(["Comparación", comparison.status])
        sheet.append(
            [
                "Advertencia",
                "Evaluación parcial; no habilita aprobación."
                if not analysis.coverage.complete
                else "Requiere decisión FinOps autorizada.",
            ]
        )
        sheet["A1"].font = Font(bold=True, size=16, color="FFFFFF")
        sheet["A1"].fill = self.HEADER_FILL
        sheet["B1"].fill = self.HEADER_FILL
        sheet["B10"].number_format = "0.0%"
        sheet["B11"].number_format = "0.0%"
        for cell in ("B8", "B9", "B12", "B13"):
            sheet[cell].number_format = "#,##0.00"

    def _costs(self, sheet, intake, analysis):
        headers = [
            "Recurso",
            "Servicio AWS",
            "Estado",
            "Costo mensual",
            "Costo anual",
            "Evidencia",
        ]
        sheet.append(headers)
        breakdown = {item.resource_id: item for item in analysis.breakdown}
        rows = []
        for resource in intake.handoff.architecture.resources:
            row = sheet.max_row + 1
            item = breakdown.get(resource.resource_id)
            if item:
                sheet.append(
                    [
                        resource.resource_id,
                        resource.aws_service,
                        "Verificado",
                        float(item.monthly_cost),
                        f"=D{row}*12",
                        item.evidence_id,
                    ]
                )
            else:
                sheet.append(
                    [
                        resource.resource_id,
                        resource.aws_service,
                        "Pendiente",
                        None,
                        f'=IF(D{row}="","",D{row}*12)',
                        None,
                    ]
                )
                for cell in sheet[row]:
                    cell.fill = self.PENDING_FILL
            rows.append((row, resource.resource_id, resource.aws_service, bool(item)))
        total = sheet.max_row + 1
        sheet.append(
            [
                "TOTAL VERIFICADO",
                None,
                "Parcial" if not analysis.coverage.complete else "Completo",
                f"=SUM(D2:D{total - 1})",
                f"=SUM(E2:E{total - 1})",
                None,
            ]
        )
        for cell in sheet[total]:
            cell.font = Font(bold=True)
        return rows

    def _projection(self, sheet, cost_rows):
        months = [
            "Ene",
            "Feb",
            "Mar",
            "Abr",
            "May",
            "Jun",
            "Jul",
            "Ago",
            "Sep",
            "Oct",
            "Nov",
            "Dic",
        ]
        sheet.append(["Recurso", *months, "Total anual", "Estado"])
        for cost_row, resource_id, _, verified in cost_rows:
            row = sheet.max_row + 1
            values = [resource_id]
            values.extend([f"=Costos!D{cost_row}" if verified else None] * 12)
            values.extend(
                [
                    f'=IF(COUNTA(B{row}:M{row})=0,"",SUM(B{row}:M{row}))',
                    "Verificado" if verified else "Pendiente",
                ]
            )
            sheet.append(values)
            if not verified:
                for cell in sheet[row]:
                    cell.fill = self.PENDING_FILL
        total = sheet.max_row + 1
        sheet.append(
            [
                "TOTAL VERIFICADO",
                *[
                    f"=SUM({get_column_letter(column)}2:{get_column_letter(column)}{total - 1})"
                    for column in range(2, 14)
                ],
                f"=SUM(B{total}:M{total})",
                None,
            ]
        )

    def _scenarios(self, sheet, analysis):
        sheet.append(
            [
                "Escenario",
                "Estado",
                "Costo mensual",
                "Costo anual",
                "Evidencias",
                "Bloqueos",
            ]
        )
        names = {
            "base": "Base",
            "higher_demand": "Mayor demanda",
            "lower_demand": "Menor demanda",
            "optimized": "Optimización",
        }
        for scenario in analysis.scenarios:
            row = sheet.max_row + 1
            sheet.append(
                [
                    names[scenario.scenario],
                    scenario.status,
                    float(scenario.monthly_cost)
                    if scenario.monthly_cost is not None
                    else None,
                    f'=IF(C{row}="","",C{row}*12)',
                    ", ".join(scenario.evidence_ids),
                    "; ".join(scenario.blocking_reasons),
                ]
            )
            if scenario.status != "evaluated":
                for cell in sheet[row]:
                    cell.fill = self.PENDING_FILL

    def _evidence(self, sheet, evidence):
        sheet.append(
            [
                "Execution ID",
                "Servicio",
                "Región",
                "URL",
                "Fecha",
                "Estado",
                "Artefacto",
                "Tipo",
                "SHA-256",
            ]
        )
        for item in evidence:
            if item.artifacts:
                for artifact in item.artifacts:
                    sheet.append(
                        [
                            item.execution_id,
                            item.aws_service,
                            item.region,
                            item.estimate_url,
                            item.executed_at.isoformat(),
                            item.status,
                            artifact.path,
                            artifact.artifact_type,
                            artifact.sha256,
                        ]
                    )
            else:
                sheet.append(
                    [
                        item.execution_id,
                        item.aws_service,
                        item.region,
                        item.estimate_url,
                        item.executed_at.isoformat(),
                        item.status,
                        None,
                        None,
                        None,
                    ]
                )

    def _assumptions(self, sheet, intake):
        sheet.append(
            [
                "Recurso",
                "Dimensión",
                "Métrica",
                "Cantidad",
                "Unidad",
                "Periodo",
                "Fuente",
                "Requisito",
                "Estado / motivo",
            ]
        )
        contract = intake.handoff.economic_contract
        for pricing in contract.pricing_inputs:
            for dimension in pricing.dimensions:
                source = dimension.source
                status = (
                    "Conocido"
                    if dimension.quantity is not None
                    else (dimension.missing_reason or "Desconocido")
                )
                sheet.append(
                    [
                        pricing.resource_id,
                        dimension.dimension_id,
                        dimension.metric,
                        float(dimension.quantity)
                        if dimension.quantity is not None
                        else None,
                        dimension.unit,
                        dimension.period,
                        source.source_type,
                        source.source_reference,
                        status,
                    ]
                )

    def _finish(self, workbook):
        for sheet in workbook.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = self.HEADER_FILL
                cell.alignment = Alignment(wrap_text=True)
            for column in range(1, sheet.max_column + 1):
                values = [
                    str(sheet.cell(row, column).value or "")
                    for row in range(1, sheet.max_row + 1)
                ]
                sheet.column_dimensions[get_column_letter(column)].width = min(
                    max(max(map(len, values)) + 2, 12), 48
                )
            for row in sheet.iter_rows():
                for cell in row:
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
            if sheet.title in {"Costos", "Proyección", "Escenarios"}:
                for row in sheet.iter_rows(min_row=2):
                    for cell in row:
                        if cell.column in {
                            3,
                            4,
                            5,
                            6,
                            7,
                            8,
                            9,
                            10,
                            11,
                            12,
                            13,
                            14,
                        } and isinstance(cell.value, (int, float)):
                            cell.number_format = "#,##0.00"
