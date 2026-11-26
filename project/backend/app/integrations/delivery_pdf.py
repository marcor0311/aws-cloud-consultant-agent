"""Executive draft renderer: only display documented facts and their provenance."""

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.delivery.models import DemoRequest, EngineeringHandoff

NAVY = colors.HexColor("#16324F")
TEAL = colors.HexColor("#087E8B")
LIGHT = colors.HexColor("#EFF5F8")
PHASE_NAMES = {
    "discovery": "Descubrimiento",
    "prioritization": "Priorización",
    "architecture": "Arquitectura",
    "finops": "FinOps",
    "engineering": "Ingeniería",
    "report": "Informe",
}


def render_pdf(
    request: DemoRequest,
    handoff: EngineeringHandoff,
    metrics: dict,
    *,
    version: int = 1,
    revision_text: str | None = None,
    approval: dict | None = None,
) -> bytes:
    font_dir = Path(reportlab.__file__).parent / "fonts"
    for name, filename in (("Delivery", "Vera.ttf"), ("DeliveryBold", "VeraBd.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "DeliveryBody",
        fontName="Delivery",
        fontSize=9,
        leading=14,
        spaceAfter=6,
        textColor=NAVY,
        splitLongWords=True,
    )
    heading = ParagraphStyle(
        "DeliveryHeading",
        parent=body,
        fontName="DeliveryBold",
        fontSize=12,
        leading=17,
        spaceBefore=11,
        spaceAfter=6,
        keepWithNext=True,
    )
    small = ParagraphStyle("DeliverySmall", parent=body, fontSize=7.5, leading=11)
    title = ParagraphStyle(
        "DeliveryTitle",
        parent=styles["Title"],
        fontName="DeliveryBold",
        fontSize=24,
        leading=30,
        alignment=0,
        textColor=NAVY,
        spaceAfter=12,
    )

    def paragraph(text, style=body):
        return Paragraph(escape(str(text)), style)

    def table(rows, widths, header=True):
        rendered = [[paragraph(cell, small) for cell in row] for row in rows]
        result = Table(
            rendered, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT"
        )
        commands = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E3EA")),
        ]
        if header:
            commands.extend([("BACKGROUND", (0, 0), (-1, 0), LIGHT)])
        result.setStyle(TableStyle(commands))
        return result

    content = BytesIO()
    doc = SimpleDocTemplate(
        content,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=27 * mm,
        bottomMargin=20 * mm,
        title=f"Informe ejecutivo v{version} - {request.project_name}",
        author="PSWE-07 / flujo local",
    )
    width = A4[0] - 36 * mm
    story = [
        paragraph("Informe ejecutivo", title),
        paragraph(request.project_name, heading),
        paragraph(
            f"Proyecto {request.project_id} | Entrega {request.delivery_id}", small
        ),
        paragraph(
            f"Fecha de corte: {handoff.created_at.isoformat()} | Versión del informe: {version}",
            small,
        ),
    ]
    notice = Table(
        [
            [
                paragraph(
                    (
                        "APROBADO PARA DEMOSTRACIÓN. "
                        if approval
                        else "BORRADOR DE DEMOSTRACIÓN. "
                    )
                    + "Arquitectura y costos simulados. Sin despliegue AWS, PR técnico del proyecto ni aprobación del arquitecto.",
                    small,
                )
            ]
        ],
        colWidths=[width],
    )
    notice.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF3D6")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D9A441")),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend(
        [
            Spacer(1, 9),
            notice,
            paragraph("1. Resultado y alcance", heading),
            paragraph(handoff.summary),
            paragraph(
                "Se preparó una composición Terraform S3 con referencia fija al catálogo. La tabla identifica las verificaciones registradas y su alcance en el emulador."
            ),
        ]
    )
    costs = request.finops
    remaining = costs.budget_monthly - costs.estimate_monthly
    story.extend(
        [
            paragraph("2. Presupuesto y estimación", heading),
            table(
                [
                    ["Concepto", "Monto mensual", "Origen"],
                    [
                        "Presupuesto autorizado de ejemplo",
                        f"{costs.currency} {costs.budget_monthly:,.2f}",
                        "Simulado",
                    ],
                    [
                        "Estimación FinOps de ejemplo",
                        f"{costs.currency} {costs.estimate_monthly:,.2f}",
                        "Simulado",
                    ],
                    [
                        "Margen respecto al presupuesto",
                        f"{costs.currency} {remaining:,.2f}",
                        "Calculado sobre datos simulados",
                    ],
                    ["Gasto real", "No disponible", "No hubo despliegue AWS"],
                ],
                [width * 0.46, width * 0.24, width * 0.30],
            ),
            paragraph("Supuestos: " + " ".join(costs.assumptions)),
            paragraph("Calculadora: " + costs.calculator_reference, small),
            paragraph("Excel: " + costs.spreadsheet_reference, small),
        ]
    )
    story.append(paragraph("3. Validaciones y revisión", heading))
    status_names = {
        "passed": "Correcta",
        "failed": "Fallida",
        "not_run": "No ejecutada",
    }
    category_names = {
        "terraform": "Terraform",
        "security": "Análisis estático",
        "emulator": "Conexión al emulador",
        "integration": "Integración con AWS Emulator",
        "policy": "Política como código",
        "cleanup": "Limpieza del entorno",
    }
    story.append(
        table(
            [["Comprobación", "Resultado", "Detalle"]]
            + [
                [
                    check.name,
                    status_names[check.status],
                    category_names.get(check.detail, check.detail),
                ]
                for check in handoff.checks
            ],
            [width * 0.26, width * 0.20, width * 0.54],
        )
    )
    story.append(
        paragraph(
            "Estado: implementación preparada; revisión técnica pendiente; sin PR ni integración. La aprobación simulada de los insumos no es una aprobación real del arquitecto."
        )
    )
    if revision_text:
        story.append(paragraph("Actualización del Engagement Manager", heading))
        story.append(paragraph(revision_text))
    story.append(paragraph("4. Tiempos observados por fase", heading))
    timing_rows = [
        ["Fase / origen", "Lead Time", "PT", "Espera", "Retrabajo", "Esfuerzo H / A"]
    ]
    for row in metrics["phases"]:

        def seconds(value):
            return f"{value:.3f} s" if value < 1 else f"{value:,.1f} s"

        timing_rows.append(
            [
                PHASE_NAMES[row["phase"]]
                + (" / real" if row["provenance"] == "real" else " / simulado"),
                seconds(row["lead_time_seconds"]),
                seconds(row["process_time_seconds"]),
                seconds(row["wait_seconds"]),
                seconds(row["rework_effort_seconds"]),
                seconds(row["human_effort_seconds"])
                + " / "
                + seconds(row["agent_effort_seconds"]),
            ]
        )
    story.append(
        table(
            timing_rows,
            [
                width * 0.23,
                width * 0.15,
                width * 0.13,
                width * 0.13,
                width * 0.14,
                width * 0.20,
            ],
        )
    )
    story.append(
        paragraph(
            "PT = esfuerzo activo acumulado humano y agente. H / A muestra su desglose. Con paralelismo, PT puede superar el tiempo transcurrido. La espera se obtiene de intervalos explícitos.",
            small,
        )
    )
    missing = ", ".join(PHASE_NAMES[p] for p in metrics["missing_phases"])
    story.append(
        paragraph(
            "Sin medición completa al corte: "
            + (missing or "ninguna")
            + ". El propio informe se termina después de este corte; su tiempo final queda disponible en la API.",
            small,
        )
    )
    story.append(paragraph(metrics["note"], small))
    story.append(paragraph("5. Pendientes y siguientes pasos", heading))
    for index, item in enumerate(handoff.pending_items, 1):
        story.append(paragraph(f"{index}. {item}"))
    story.append(paragraph("6. Fuentes y respaldo", heading))
    for label, value in (
        (
            "Arquitectura simulada",
            request.architecture.source.reference
            + " @ "
            + request.architecture.source.revision,
        ),
        ("FinOps simulado", costs.source.reference + " @ " + costs.source.revision),
        (
            "Catálogo de módulos",
            request.architecture.baseline.repository
            + " @ "
            + request.architecture.baseline.commit,
        ),
    ):
        story.append(paragraph(f"{label}: {value}", small))
    if evidence := handoff.inputs.get("emulator_evidence"):
        story.append(paragraph(f"Evidencia AWS Emulator: {evidence['source']}", small))
        versions = evidence["versions"]
        if versions.get("aws_emulator") and versions.get("terraform_version"):
            story.append(
                paragraph(
                    f"{versions['aws_emulator']} | Terraform {versions['terraform_version']}",
                    small,
                )
            )
    for artifact in handoff.artifacts:
        story.append(
            paragraph(
                f"Archivo generado: {artifact.filename} | ID {artifact.artifact_id} | SHA-256 {artifact.sha256}",
                small,
            )
        )
    if approval:
        story.append(
            KeepTogether(
                [
                    paragraph("Aprobación del Engagement Manager", heading),
                    paragraph(f"{approval['operator']} | {approval['at']}", small),
                    paragraph(approval["detail"], small),
                    paragraph(
                        f"SHA-256 de la revisión aprobada: {approval['sha256']}", small
                    ),
                ]
            )
        )
    else:
        story.append(paragraph("Aprobación del Engagement Manager: pendiente.", small))

    def page(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(TEAL)
        canvas.setLineWidth(2)
        canvas.line(18 * mm, A4[1] - 18 * mm, A4[0] - 18 * mm, A4[1] - 18 * mm)
        canvas.setFillColor(NAVY)
        canvas.setFont("DeliveryBold", 8)
        canvas.drawString(18 * mm, A4[1] - 14 * mm, "CONSULTORÍA AWS / PSWE-07")
        canvas.setFont("Delivery", 7)
        canvas.drawRightString(
            A4[0] - 18 * mm, A4[1] - 14 * mm, f"INFORME V{version} / DEMO LOCAL"
        )
        canvas.drawString(
            18 * mm,
            12 * mm,
            "APROBADO / DEMO" if approval else "BORRADOR / DEMO",
        )
        canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"Página {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=page, onLaterPages=page)
    return content.getvalue()


def render_case_pdf(snapshot, sections, *, version, source, approval=None):
    """Corporate report from recorded facts; missing values stay visible."""
    from datetime import UTC, datetime

    font_dir = Path(reportlab.__file__).parent / "fonts"
    for name, filename in (("Delivery", "Vera.ttf"), ("DeliveryBold", "VeraBd.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))
    body = ParagraphStyle(
        "CaseBody",
        fontName="Delivery",
        fontSize=9,
        leading=14,
        spaceAfter=7,
        textColor=NAVY,
    )
    heading = ParagraphStyle(
        "CaseHeading",
        parent=body,
        fontName="DeliveryBold",
        fontSize=12,
        leading=17,
        spaceBefore=12,
        keepWithNext=True,
    )
    small = ParagraphStyle("CaseSmall", parent=body, fontSize=7.5, leading=11)

    def para(value, style=body):
        return Paragraph(escape(str(value)), style)

    def seconds(value):
        return "Sin medición" if value is None else f"{value:,.1f} s"

    width = A4[0] - 36 * mm

    def table(rows, ratios):
        result = Table(
            [[para(c, small) for c in row] for row in rows],
            colWidths=[width * r for r in ratios],
            repeatRows=1,
            hAlign="LEFT",
        )
        result.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E3EA")),
                ]
            )
        )
        return result

    project, metrics = snapshot["project"], snapshot["metrics"]
    partial = bool(snapshot["closure_blockers"])
    stamp = datetime.fromtimestamp(snapshot["captured_at"], UTC).isoformat()
    title = ParagraphStyle("CaseTitle", parent=heading, fontSize=24, leading=30)
    story = [
        para("Informe ejecutivo", title),
        para(project["title"], heading),
        para(
            f"Expediente {snapshot['case_id']} | Versión {version} | Corte {stamp}",
            small,
        ),
        para(
            ("INFORME PARCIAL APROBADO" if partial else "INFORME DEFINITIVO APROBADO")
            if approval
            else ("BORRADOR PARCIAL" if partial else "BORRADOR DEFINITIVO"),
            heading,
        ),
        para(
            "Proyecto ficticio. "
            if project["is_fictitious"]
            else "Expediente registrado. "
        ),
        para(
            "La aprobación de este documento no acredita aprobación técnica ni cierra el proyecto. Las fuentes faltantes o simuladas se indican expresamente."
        ),
        para("1. Resultados", heading),
        para(sections["results"]),
        para("2. Presupuesto y costos", heading),
    ]
    budget = snapshot["budget"]
    story.append(
        para(
            f"Presupuesto registrado por dirección: {budget['currency']} {budget['total']}. Periodo no especificado en el registro; no se compara con una estimación mensual."
            if budget
            else "Presupuesto de dirección: sin información registrada."
        )
    )
    technical = snapshot["technical"]
    engineering = snapshot.get("engineering")
    check_status = {
        "passed": "Correcta informada",
        "failed": "Fallida informada",
        "not_run": "No ejecutada",
    }
    if engineering:
        inputs = engineering["intake"]["input"]
        period = "mes" if inputs["period"] == "month" else "año"
        label = "ficticio" if engineering["intake"]["is_fictitious"] else "registrado"
        story.extend(
            [
                para(
                    f"FinOps ({label}): presupuesto {inputs['currency']} {inputs['budget']} por {period}; estimación {inputs['currency']} {inputs['estimate']} por {period}."
                ),
                para(f"Calculadora registrada: {inputs['calculator_url']}", small),
                para(
                    "Excel de costos: "
                    + next(
                        f["reference"]
                        for f in inputs["finops"]["files"]
                        if f["role"] == "cost_workbook"
                    ),
                    small,
                ),
                para("3. Validaciones y evidencias de ingeniería", heading),
                para(
                    "Se verificó la integridad de los archivos registrados. Los resultados de ejecución fueron declarados por el operador; generar este informe no ejecuta ni autentica las pruebas."
                ),
                para(
                    "Insumos vigentes para esta recepción."
                    if engineering["upstream_current"]
                    else "La recepción requiere conciliación con el estado actual del proceso antes de continuar."
                ),
            ]
        )
        latest = engineering["evidence"][-1] if engineering["evidence"] else None
        if latest:
            execution = latest["evidence"]
            story.extend(
                [
                    para(f"Corrida seleccionada: {latest['run_id']}", small),
                    para(
                        f"Commit de implementación declarado: {execution['implementation_commit']}",
                        small,
                    ),
                    para(f"Origen de la corrida: {execution['run_reference']}", small),
                    table(
                        [["Comprobación", "Resultado", "Detalle informado"]]
                        + [
                            [
                                c["name"],
                                check_status[c["status"]],
                                c["detail"]
                                + (
                                    " | Origen del fallo: " + c["failure_origin"]
                                    if c.get("failure_origin")
                                    else ""
                                ),
                            ]
                            for c in execution["checks"]
                        ],
                        [0.30, 0.22, 0.48],
                    ),
                    para("Versiones de la corrida", heading),
                    table(
                        [["Herramienta", "Versión registrada"]]
                        + [
                            [name, value]
                            for name, value in execution["versions"].items()
                        ],
                        [0.35, 0.65],
                    ),
                    para(
                        "Recursos informados: " + ", ".join(execution["resources"]),
                        small,
                    ),
                ]
            )
        else:
            story.append(
                para(
                    "Recepción registrada sin corridas técnicas importadas. Las comprobaciones permanecen pendientes."
                )
            )
        story.extend(
            [
                para("Módulos y revisiones de referencia", heading),
                table(
                    [["Módulo", "Commit fijado"]]
                    + [
                        [m["repository"] + "/" + m["path"], m["commit"]]
                        for m in inputs["modules"]
                    ],
                    [0.45, 0.55],
                ),
                para(
                    "Referencias de aprobación de baselines pendientes de verificación externa. Revisión del arquitecto y PR de implementación pendientes."
                    if not engineering.get("release")
                    else "Aprobación técnica contrastada con el proceso. Código, revisión, baselines, estado de CI y protección de main verificados mediante la API de GitHub; los logs locales conservan su procedencia declarada."
                    if engineering["release"].get("external_verification")
                    else "Aprobación técnica contrastada con el proceso. Referencias de GitHub, protección de main y baselines confirmadas por el operador; sin autenticación remota automática."
                ),
            ]
        )
        if release_record := engineering.get("release"):
            release = release_record["release"]
            story.extend(
                [
                    para("Entrega técnica definitiva", heading),
                    para(f"PR: {release['pull_request']}", small),
                    para(
                        f"Arquitecto: {release['architect']} | Revisión: {release['review_reference']}",
                        small,
                    ),
                    para(f"Commit probado: {release['implementation_commit']}", small),
                    para(f"Integración: {release['integration_reference']}", small),
                    para(
                        f"Corridas local / CI: {release['local_run_id']} / {release['ci_run_id']}",
                        small,
                    ),
                    para(
                        f"Catálogo de compatibilidad: revisión {release_record['catalog']['revision']} | SHA-256: {release_record['catalog']['sha256']}",
                        small,
                    ),
                ]
            )
            story.extend(
                para(limit, small) for limit in release["compatibility_limits"]
            )
    elif technical:
        costs = technical["costs"]
        check_status = {
            "passed": "Correcta",
            "failed": "Fallida",
            "not_run": "No ejecutada",
        }
        story.extend(
            [
                para(
                    f"Estimación FinOps simulada: {costs['currency']} {costs['estimate_monthly']} por mes. Presupuesto mensual del ejemplo: {costs['budget_monthly']}."
                ),
                para(f"Calculadora (simulada): {costs['calculator_reference']}", small),
                para(f"Excel (simulado): {costs['spreadsheet_reference']}", small),
                para("3. Validaciones y entrega técnica", heading),
                table(
                    [["Comprobación", "Estado", "Alcance"]]
                    + [
                        [c["name"], check_status[c["status"]], c["detail"]]
                        for c in technical["checks"]
                    ],
                    [0.30, 0.17, 0.53],
                ),
                para(
                    "Revisión técnica pendiente. Sin PR de implementación integrado. Insumos de arquitectura y FinOps simulados."
                ),
            ]
        )
    else:
        story.extend(
            [
                para("Estimación FinOps, calculadora y Excel: pendientes."),
                para("3. Validaciones y entrega técnica", heading),
                para(
                    "Sin entrega técnica adjunta. No se ejecutó ingeniería para generar este informe."
                ),
            ]
        )
    story.append(para("Gasto real AWS: no disponible."))
    story.append(para("4. Tiempos registrados", heading))

    def rework(phase):
        total = phase.get("rework_effort_seconds")
        recorded = phase.get("recorded_rework_effort_seconds")
        if total is not None:
            return seconds(total)
        return (
            seconds(recorded) + " (parcial)" if recorded is not None else "Sin medición"
        )

    story.append(
        table(
            [
                [
                    "Fase",
                    "LT al corte",
                    "PT esfuerzo",
                    "Activa",
                    "Espera",
                    "Retrabajo",
                    "Humano / agente",
                ]
            ]
            + [
                [
                    PHASE_NAMES[p["phase"]]
                    + (" (en curso)" if p["in_progress"] else ""),
                    seconds(p["lead_time_seconds"]),
                    seconds(p["process_time_seconds"]),
                    seconds(p["active_elapsed_seconds"]),
                    seconds(p["wait_seconds"]),
                    rework(p),
                    f"{seconds(p['human_effort_seconds'])} / {seconds(p['agent_effort_seconds'])}",
                ]
                for p in metrics["phases"]
            ],
            [0.18, 0.12, 0.12, 0.12, 0.12, 0.12, 0.22],
        )
    )
    story.extend(
        [
            para(metrics["note"], small),
            para(
                "El retrabajo marcado como parcial muestra solo intervalos clasificados; no estima la parte sin medición.",
                small,
            ),
            para(
                f"Ciclos de ajustes observados: {metrics['rework_cycles']}; devoluciones del proceso: {metrics['process_rework_cycles']}. Su duración no se infiere del número de eventos.",
                small,
            ),
            para(
                "La tabla corresponde al corte previo a generar este PDF. El tiempo de generación y revisión del propio informe se consulta por separado.",
                small,
            ),
        ]
    )

    def phase_label(phase):
        names = {f"stage-{n}": name for n, name in enumerate(PHASE_NAMES.values(), 1)}
        return names.get(phase, phase)

    if metrics["handoffs"]:
        story.append(para("Entregas y espera de recepción", heading))
        story.append(
            table(
                [["Entrega", "Espera de recepción", "Estado"]]
                + [
                    [
                        f"{phase_label(h['from_phase'])} a {phase_label(h['to_phase'])}",
                        seconds(h["wait_seconds"]),
                        "Pendiente" if h["pending_acceptance"] else "Recibida",
                    ]
                    for h in metrics["handoffs"]
                ],
                [0.48, 0.27, 0.25],
            )
        )
    for label, key in (("5. Riesgos", "risks"), ("6. Siguientes pasos", "next_steps")):
        story.extend([para(label, heading), para(sections[key])])
    story.append(para("Requisitos pendientes para el cierre", heading))
    story.extend(para(item) for item in snapshot["closure_blockers"])
    if not partial:
        story.append(
            para(
                "Entrega técnica definitiva registrada. El cierre requiere aprobación de esta revisión y registro de su presentación a dirección."
            )
        )
    story.append(para("7. Decisiones y fuentes", heading))
    if engineering:
        story.append(
            para(
                f"Recepción: {engineering['intake']['intake_id']} | SHA-256 de entrada: {engineering['intake']['input_sha256']}",
                small,
            )
        )
        for run in engineering["evidence"]:
            story.append(
                para(
                    f"Corrida registrada: {run['run_id']} | SHA-256 del manifiesto: {run['evidence_sha256']}",
                    small,
                )
            )
        for file in engineering["files"]:
            story.append(
                para(f"Respaldo: {file['path']} | SHA-256: {file['sha256']}", small)
            )
    for d in snapshot["decisions"]:
        event = d["payload"]
        label = {
            "stage.changes_requested": "Solicitud de cambios",
            "stage.approved": "Aprobación de etapa",
            "stage.rejected": "Rechazo de dirección",
            "deliverable.ready": "Entregable disponible",
            "opening.approved": "Apertura aprobada",
            "opening.rejected": "Apertura rechazada",
            "approval.decided": "Decisión de revisión",
        }.get(event.get("kind", d["kind"]), "Decisión registrada")
        story.append(
            para(
                f"{label} | Responsable: {event.get('actor', 'Sin registro')} | Referencia: {d['id']}",
                small,
            )
        )
    for s in snapshot["sources"]:
        provenance = {
            "fictitious": "Ficticia",
            "recorded": "Registrada",
            "simulated_inputs": "Insumos simulados",
            "operator_recorded": "Declarada por el operador; integridad verificada",
        }[s["provenance"]]
        story.append(para(f"{s['reference']} | Procedencia: {provenance}", small))
    story.extend(
        [
            para(f"Respaldo: {source['filename']}", small),
            para(f"SHA-256: {source['sha256']}", small),
        ]
    )
    if approval:
        story.extend(
            [
                para(
                    "Aprobación del informe parcial"
                    if partial
                    else "Aprobación del informe definitivo",
                    heading,
                ),
                para(f"{approval['operator']} | {approval['at']}", small),
                para(approval["detail"]),
                para(f"SHA-256 de la revisión aprobada: {approval['sha256']}", small),
            ]
        )

    def page(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(TEAL)
        canvas.setLineWidth(2)
        canvas.line(18 * mm, A4[1] - 18 * mm, A4[0] - 18 * mm, A4[1] - 18 * mm)
        canvas.setFillColor(NAVY)
        canvas.setFont("DeliveryBold", 8)
        canvas.drawString(18 * mm, A4[1] - 14 * mm, "CONSULTORÍA AWS / PSWE-07")
        canvas.setFont("Delivery", 7)
        canvas.drawString(
            18 * mm,
            12 * mm,
            f"INFORME {'PARCIAL' if partial else 'DEFINITIVO'} V{version}",
        )
        canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"Página {doc.page}")
        canvas.restoreState()

    output = BytesIO()
    SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=25 * mm,
        bottomMargin=20 * mm,
        title=f"Informe ejecutivo - {project['title']}",
    ).build(story, onFirstPage=page, onLaterPages=page)
    return output.getvalue()
