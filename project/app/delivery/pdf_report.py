"""Executive draft renderer: only display documented facts and their provenance."""

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from app.delivery.models import DemoRequest, EngineeringHandoff
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
    request: DemoRequest, handoff: EngineeringHandoff, metrics: dict
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
        spaceAfter=7,
        textColor=NAVY,
        splitLongWords=True,
    )
    heading = ParagraphStyle(
        "DeliveryHeading",
        parent=body,
        fontName="DeliveryBold",
        fontSize=12,
        leading=17,
        spaceBefore=14,
        spaceAfter=8,
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
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
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
        title=f"Borrador ejecutivo - {request.project_name}",
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
            f"Fecha de corte: {handoff.created_at.isoformat()} | Versión del informe: 1",
            small,
        ),
    ]
    notice = Table(
        [
            [
                paragraph(
                    "BORRADOR DE DEMOSTRACIÓN. Arquitectura y costos simulados. Sin despliegue AWS, sin PR técnico ni aprobación del arquitecto. No acredita cierre del proyecto.",
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
                "Se preparó una composición Terraform S3 con referencia fija al catálogo. Las verificaciones de esta entrega cubren la coherencia de los insumos y la generación de archivos; no acreditan seguridad ni funcionamiento de infraestructura desplegada."
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
            paragraph("Supuestos: " + "; ".join(costs.assumptions)),
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
    story.append(
        table(
            [["Comprobación", "Resultado", "Detalle"]]
            + [
                [check.name, status_names[check.status], check.detail]
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
    story.append(paragraph("4. Tiempos observados por fase", heading))
    timing_rows = [
        ["Fase / origen", "Lead Time", "PT / esfuerzo", "Espera", "Esfuerzo H / A"]
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
                seconds(row["human_effort_seconds"])
                + " / "
                + seconds(row["agent_effort_seconds"]),
            ]
        )
    story.append(
        table(
            timing_rows,
            [width * 0.27, width * 0.16, width * 0.16, width * 0.16, width * 0.25],
        )
    )
    story.append(
        paragraph(
            "PT = esfuerzo activo acumulado humano y agente; H / A muestra su desglose. Con paralelismo, PT puede superar el tiempo transcurrido. La duración activa sin solapamiento y el retrabajo se desglosan en la API. La espera se obtiene de intervalos explícitos, no restando PT al Lead Time.",
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
    for artifact in handoff.artifacts:
        story.append(
            paragraph(
                f"Archivo generado: {artifact.filename} | ID {artifact.artifact_id} | SHA-256 {artifact.sha256}",
                small,
            )
        )
    story.append(
        paragraph(
            "Aprobación del Engagement Manager: pendiente. Este avance permite revisar el borrador; ajustes versionados, aprobación formal, MCP y cierre son incrementos posteriores.",
            small,
        )
    )

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
            A4[0] - 18 * mm, A4[1] - 14 * mm, "ENTREGA 1 / DEMO LOCAL"
        )
        canvas.drawString(
            18 * mm,
            12 * mm,
            "BORRADOR - datos simulados identificados - sin aprobación",
        )
        canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"Página {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=page, onLaterPages=page)
    return content.getvalue()
