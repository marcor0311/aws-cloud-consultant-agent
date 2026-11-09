"""ReportLab documents and a standalone HTML deck from validated meeting content."""

import base64
import hashlib
import json
import os
import re
import tempfile
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.preparation.insumos import MeetingInsumos, MeetingTranscript, meeting_date

ASSETS = Path(__file__).with_name("insumos_assets")
FILENAMES = (
    "resumen-reunion.pdf",
    "ficha-proyecto.pdf",
    "presentacion.html",
    "presentacion.pdf",
)
INK = colors.HexColor("#152536")
BLUE = colors.HexColor("#244cdd")
MUTED = colors.HexColor("#526171")
LINE = colors.HexColor("#d4dce5")
WIDTH, HEIGHT = A4
CONTENT_WIDTH = WIDTH - 104
BRAND = "No Name"


def editorial_text(text):
    """Translate display labels without changing source evidence."""
    text = re.sub(r"\bBrief\b", "Ficha", text)
    text = re.sub(r"\bbrief\b", "ficha del proyecto", text)
    return text.replace(
        "Engagement Manager", "Responsable de la relación con el cliente"
    )


def heading_text(text):
    return "\n".join(
        line.rstrip().rstrip(".") for line in editorial_text(text).splitlines()
    )


def number(value):
    return f"{value:,}".replace(",", ".")


def styles():
    for suffix in ("Regular", "Bold"):
        name = f"Lato-{suffix}"
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(ASSETS / f"fonts/{name}.ttf")))
    pdfmetrics.registerFontFamily(
        "Lato-Regular", normal="Lato-Regular", bold="Lato-Bold"
    )
    sheet = getSampleStyleSheet()
    settings = {
        "Body": dict(fontName="Lato-Regular", fontSize=10.4, leading=15, spaceAfter=9),
        "Small": dict(
            fontName="Lato-Regular",
            fontSize=8.2,
            leading=11.5,
            textColor=MUTED,
            spaceAfter=6,
        ),
        "Kicker": dict(
            fontName="Lato-Bold",
            fontSize=8.3,
            leading=12,
            spaceAfter=12,
            textColor=MUTED,
        ),
        "Cover": dict(fontName="Lato-Bold", fontSize=35, leading=38, spaceAfter=13),
        "Title": dict(fontName="Lato-Bold", fontSize=27, leading=31, spaceAfter=16),
        "Section": dict(
            fontName="Lato-Bold",
            fontSize=11.5,
            leading=15,
            textColor=BLUE,
            spaceBefore=17,
            spaceAfter=9,
            keepWithNext=True,
        ),
        "Item": dict(fontName="Lato-Regular", fontSize=10, leading=14, spaceAfter=8),
        "Cell": dict(fontName="Lato-Regular", fontSize=9.4, leading=13.2, spaceAfter=0),
        "Metric": dict(fontName="Lato-Bold", fontSize=29, leading=33, spaceAfter=5),
        "Quote": dict(fontName="Lato-Regular", fontSize=14, leading=20, spaceAfter=12),
    }
    for name, values in settings.items():
        sheet.add(
            ParagraphStyle(
                f"Insumos{name}", alignment=TA_LEFT, **{"textColor": INK, **values}
            )
        )
    return {name: sheet[f"Insumos{name}"] for name in settings}


def paragraph(text, style, refs=None):
    if style.name in {
        "InsumosCover",
        "InsumosTitle",
        "InsumosSection",
        "InsumosKicker",
    }:
        text = heading_text(text)
    value = escape(editorial_text(text)).replace("\n", "<br/>")
    if refs:
        value += f' <font size="7.4" color="#777777">[{", ".join(refs)}]</font>'
    return Paragraph(value, style)


def points(values, sheet, *, compact=False):
    result = []
    for point in values:
        prefix = {"confirmed": "", "proposed": "Propuesta: ", "pending": "Pendiente: "}[
            point.status
        ]
        result.append(
            paragraph(
                prefix + point.text, sheet["Item" if compact else "Body"], point.sources
            )
        )
    return result


def metric_strip(content, sheet, *, compact=False):
    cells = []
    for metric in content.metrics:
        cells.append(
            [
                paragraph(number(metric.value), sheet["Metric"]),
                paragraph(metric.label, sheet["Cell"]),
                paragraph(metric.unit or "Unidad y período pendientes", sheet["Small"]),
            ]
        )
    table = Table([cells], colWidths=[CONTENT_WIDTH / 3] * 3)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 13),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9 if compact else 14),
                ("LINEBEFORE", (0, 0), (-1, -1), 0.5, LINE),
            ]
        )
    )
    return table


def document(path, transcript, label, story):
    def page_chrome(canvas, _doc):
        canvas.saveState()
        canvas.setLineWidth(1.8)
        canvas.setStrokeColor(INK)
        logo = canvas.beginPath()
        logo.moveTo(53, HEIGHT - 36)
        logo.lineTo(53, HEIGHT - 23)
        logo.lineTo(64, HEIGHT - 36)
        logo.lineTo(64, HEIGHT - 23)
        canvas.drawPath(logo)
        canvas.setFont("Lato-Bold", 12)
        canvas.setFillColor(INK)
        canvas.drawString(73, HEIGHT - 34, BRAND)
        canvas.setFont("Lato-Regular", 7.6)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(WIDTH - 52, HEIGHT - 32, label)
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.4)
        canvas.line(52, HEIGHT - 44, WIDTH - 52, HEIGHT - 44)
        canvas.setStrokeColor(BLUE)
        canvas.setLineWidth(2)
        canvas.line(52, HEIGHT - 44, 83, HEIGHT - 44)
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.4)
        canvas.line(52, 42, WIDTH - 52, 42)
        canvas.setFont("Lato-Regular", 7.3)
        tag = "Caso ficticio / " if transcript.is_mock else ""
        canvas.drawString(52, 28, tag + "Para revisión editorial")
        canvas.setFont("Lato-Regular", 8)
        canvas.drawRightString(WIDTH - 52, 28, f"Página {canvas.getPageNumber()}")
        canvas.restoreState()

    doc = BaseDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=52,
        rightMargin=52,
        topMargin=73,
        bottomMargin=55,
        title=f"{label} | {transcript.title}",
        author=BRAND,
        subject="Escenario ficticio de encuadre ejecutivo"
        if transcript.is_mock
        else "Insumos de reunión",
        invariant=1,
    )
    frame = Frame(
        52,
        55,
        CONTENT_WIDTH,
        HEIGHT - 128,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    doc.addPageTemplates(
        PageTemplate(id="monochrome", frames=frame, onPage=page_chrome)
    )
    doc.build(story)


def section(title, sheet):
    return paragraph(title, sheet["Section"])


def ruled_table(rows, widths, *, header=False):
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 15),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LINEABOVE", (0, 0), (-1, 0), 0.6, INK),
                ("LINEBELOW", (0, 0), (-1, -1), 0.35, LINE),
            ]
        )
    )
    return table


def advisory_rows(items, sheet):
    return ruled_table(
        [
            [paragraph(item.label, sheet["Cell"]), paragraph(item.text, sheet["Cell"])]
            for item in items
        ],
        [CONTENT_WIDTH * 0.29, CONTENT_WIDTH * 0.71],
    )


def source_note(refs, sheet):
    return paragraph(
        "Base documental: "
        + ", ".join(sorted(set(refs)))
        + ". Referencias a la transcripción en fuentes/.",
        sheet["Small"],
    )


def facts_strip(content, sheet):
    facts = content.facts[:3]
    if not facts:
        return metric_strip(content, sheet, compact=True)
    value_style = ParagraphStyle(
        "FactValue", parent=sheet["Title"], fontSize=19, leading=24, spaceAfter=0
    )
    label_style = ParagraphStyle(
        "FactLabel", parent=sheet["Small"], fontSize=8, leading=12, spaceAfter=5
    )
    cells = [
        [paragraph(f.label.upper(), label_style), paragraph(f.text, value_style)]
        for f in facts
    ]
    table = Table([cells], colWidths=[CONTENT_WIDTH / len(facts)] * len(facts))
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 13),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
                ("LINEABOVE", (0, 0), (-1, 0), 0.6, INK),
                ("LINEBELOW", (0, 0), (-1, 0), 0.4, LINE),
            ]
        )
    )
    return table


def actions_table(content, sheet):
    rows = [
        [
            paragraph(label, sheet["Small"])
            for label in ("ENTREGA", "RESPONSABLE", "HITO")
        ]
    ]
    rows += [
        [
            paragraph(a.task, sheet["Cell"]),
            paragraph(a.owner, sheet["Cell"]),
            paragraph(a.due, sheet["Cell"]),
        ]
        for a in content.actions
    ]
    return ruled_table(
        rows,
        [CONTENT_WIDTH * 0.49, CONTENT_WIDTH * 0.26, CONTENT_WIDTH * 0.25],
        header=True,
    )


def topic_block(topic, sheet):
    return [
        section(topic.title, sheet),
        *[paragraph(point.text, sheet["Item"]) for point in topic.points],
    ]


def render_summary(path, transcript, content):
    s = styles()
    detailed = sum(len(p.text) for t in content.topics for p in t.points) > 2400
    topic_split = 4 if detailed else 5
    started = transcript.started_at.astimezone(ZoneInfo("America/Costa_Rica"))
    ended = transcript.ended_at.astimezone(ZoneInfo("America/Costa_Rica"))
    story = [
        paragraph("RESUMEN DE REUNIÓN / ENCUADRE EJECUTIVO", s["Kicker"]),
        paragraph(transcript.project_name, s["Cover"]),
        paragraph(
            f"{meeting_date(started)} / {started:%H:%M}-{ended:%H:%M} / Costa Rica"
            + (" / Horario simulado" if transcript.is_mock else ""),
            s["Small"],
        ),
        Spacer(1, 9),
        facts_strip(content, s),
        section("Objeto y resultado de la reunión", s),
        paragraph(content.summary.split("\n\n")[0], s["Body"]),
        section("Participantes", s),
        paragraph("\n".join(transcript.participants), s["Small"]),
        section("Acuerdos del encargo", s),
        *[
            paragraph(f"{i:02d}   {point.text}", s["Item"])
            for i, point in enumerate(content.decisions, 1)
        ],
        section("Límite de la primera entrega", s),
        paragraph(" ".join(point.text for point in content.scope_out), s["Item"]),
        source_note(
            [
                *content.summary_sources,
                *(
                    ref
                    for p in content.decisions + content.scope_out
                    for ref in p.sources
                ),
            ],
            s,
        ),
        PageBreak(),
        paragraph("BASE FUNCIONAL Y TÉCNICA", s["Kicker"]),
        paragraph("Cómo se desarrollará\nel proyecto", s["Title"]),
    ]
    # The record covers each subject once. Consulting development is in the brief.
    for topic in content.topics[:topic_split]:
        story.extend(topic_block(topic, s))
    story += [
        source_note(
            [
                ref
                for t in content.topics[:topic_split]
                for p in t.points
                for ref in p.sources
            ],
            s,
        ),
        PageBreak(),
        paragraph(
            "CONTINUIDAD Y OPERACIÓN" if detailed else "COORDINACIÓN Y ENTREGA",
            s["Kicker"],
        ),
        paragraph(
            "Recuperación, demanda\ny conformidad"
            if detailed
            else "Plan de trabajo\ny responsabilidades",
            s["Title"],
        ),
    ]
    for topic in content.topics[topic_split:]:
        story.extend(topic_block(topic, s))
    if detailed:
        story += [
            section("Puntos de control", s),
            *points(content.risks, s, compact=True),
            source_note(
                [
                    ref
                    for t in content.topics[topic_split:]
                    for p in t.points
                    for ref in p.sources
                ]
                + [ref for p in content.risks for ref in p.sources],
                s,
            ),
            PageBreak(),
            paragraph("COORDINACIÓN E INVERSIÓN", s["Kicker"]),
            paragraph("Compromisos, calendario\ny condiciones económicas", s["Title"]),
        ]
    story += [
        section("Compromisos de seguimiento", s),
        actions_table(content, s),
    ]
    if not detailed:
        story += [
            section(
                "Puntos de control propuestos"
                if all(p.status == "proposed" for p in content.risks)
                else "Puntos de control",
                s,
            ),
            *[paragraph(p.text, s["Item"]) for p in content.risks],
        ]
    else:
        story += [
            section("Calendario solicitado", s),
            paragraph(content.timeline.text, s["Item"]),
        ]
    story += [
        section("Base económica y revisión", s),
        paragraph(content.budget.text, s["Item"]),
        source_note(
            [ref for a in content.actions for ref in a.sources]
            + [ref for p in content.risks for ref in p.sources]
            + content.budget.sources
            + content.timeline.sources,
            s,
        ),
    ]
    document(path, transcript, "Resumen de reunión", story)


def render_brief(path, transcript, content):
    s = styles()
    proposal = content.proposal
    executive = content.executive
    story = [
        paragraph("FICHA DEL PROYECTO / SÍNTESIS EJECUTIVA", s["Kicker"]),
        paragraph(transcript.project_name, s["Cover"]),
        paragraph(
            f"{transcript.client} / {meeting_date(transcript.started_at)}", s["Small"]
        ),
        paragraph(executive.purpose, s["Small"]) if executive else Spacer(1, 8),
        facts_strip(content, s),
    ]
    if proposal:
        story += [
            section("Recomendación de No Name", s),
            paragraph(
                executive.recommendation.text if executive else proposal.concept.text,
                s["Body"],
            ),
            section("Resultados esperados", s),
        ]
        cells = [
            [
                paragraph(f"{i:02d}", s["Kicker"]),
                paragraph(
                    item.label,
                    ParagraphStyle(
                        "ExperienceLabel",
                        parent=s["Section"],
                        spaceBefore=0,
                        spaceAfter=7,
                    ),
                ),
                paragraph(item.text, s["Item"]),
            ]
            for i, item in enumerate(
                executive.outcomes if executive else proposal.experience, 1
            )
        ]
        table = Table([cells], colWidths=[CONTENT_WIDTH / len(cells)] * len(cells))
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 18),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ("LINEABOVE", (0, 0), (-1, 0), 0.4, LINE),
                ]
            )
        )
        story += [
            table,
            section("Solución desarrollada por No Name", s),
            advisory_rows(proposal.solution, s),
        ]
    else:
        story += [
            section("El encargo", s),
            paragraph(content.summary, s["Body"]),
            section("Alcance", s),
            *points(content.scope_in, s, compact=True),
        ]
    story += [
        section("Límites del alcance", s),
        paragraph(" ".join(p.text for p in content.scope_out), s["Small"]),
        source_note(
            [ref for p in content.scope_in + content.scope_out for ref in p.sources]
            + (
                [
                    ref
                    for i in [
                        proposal.concept,
                        *proposal.experience,
                        *proposal.solution,
                    ]
                    for ref in i.sources
                ]
                if proposal
                else content.summary_sources
            ),
            s,
        ),
        PageBreak(),
        paragraph("EJECUCIÓN Y CONTROL", s["Kicker"]),
        paragraph("Plan de entrega\ny aceptación", s["Title"]),
    ]
    if proposal:
        story += [
            section("Plan de entrega", s),
            advisory_rows(proposal.delivery, s),
            section("Criterios de aceptación propuestos por No Name", s),
            advisory_rows(proposal.acceptance, s),
        ]
    else:
        story += [
            section("Criterios de aceptación", s),
            *points(content.success, s),
            section("Coordinación", s),
            actions_table(content, s),
        ]
    story += [
        section("Demanda de referencia", s),
        paragraph(
            " / ".join(
                f"{number(m.value)} {m.unit or m.context}" for m in content.metrics[:2]
            ),
            s["Item"],
        ),
    ]
    for m in content.metrics[2:]:
        story += [
            paragraph(f"{number(m.value)} {m.unit or ''}: {m.context}", s["Small"])
        ]
    story += [
        section("Dirección del proyecto e inversión", s),
        paragraph(content.budget.text, s["Item"]),
    ]
    if proposal:
        story += [
            paragraph(
                executive.oversight.label + ". " + executive.oversight.text
                if executive
                else "No Name conduce el diseño, la construcción y la validación. Marketing revisa experiencia y contenidos; Tecnología, la conexión al registro.",
                s["Small"],
            )
        ]
    story += [
        source_note(
            content.budget.sources
            + content.timeline.sources
            + (
                [
                    ref
                    for i in proposal.delivery + proposal.acceptance
                    for ref in i.sources
                ]
                if proposal
                else []
            ),
            s,
        )
    ]
    document(path, transcript, "Ficha del proyecto", story)


def render_html(path, transcript, content):
    def e(text):
        return escape(editorial_text(text), quote=True)

    def lines(text):
        return e(text).replace("\n", "<br>")

    slides = []
    total = len(content.presentation)
    for index, slide in enumerate(content.presentation, 1):
        blocks = slide.blocks
        kind = slide.kind
        note = (
            f'<div class="bottom-note reveal">{e(slide.note)}</div>'
            if slide.note
            else ""
        )
        if kind == "hero":
            image = (
                '<img class="hero-photo" src="data:image/png;base64,'
                + base64.b64encode(
                    (ASSETS / "images/corredor-editorial.png").read_bytes()
                ).decode()
                + '" alt="Corredor en movimiento, con tratamiento fotográfico azul y naranja">'
                if transcript.id == "mock-nike-maraton-cr"
                else '<div class="hero-lines" aria-hidden="true"></div>'
            )
            body = (
                image
                + f'<p class="hero-sub reveal" data-edit-id="s{index}-intro">{lines(slide.intro)}</p>'
                + '<div class="hero-accent" aria-hidden="true"></div>'
            )
        elif kind == "executive":
            facts = "".join(
                f"<article><span>{e(f.label)}</span><strong>{e(f.text)}</strong></article>"
                for f in content.facts[:3]
            )
            rows = "".join(
                f"<p><b>{e(b.label)}</b><span>{e(b.text)}</span></p>" for b in blocks
            )
            body = f'<p class="executive-purpose reveal">{e(slide.intro)}</p><div class="executive-facts reveal">{facts}</div><div class="executive-reading reveal">{rows}</div><p class="executive-note reveal">{e(slide.note)}</p>'
        elif kind == "journey":
            steps = "".join(
                f'<div class="journey-row"><b>{i:02d}</b><span>{e(text)}</span></div>'
                for i, text in enumerate(content.journey, 1)
            )
            body = f'<div class="split"><div><p class="large-copy reveal">{e(slide.intro)}</p><p class="body-copy reveal">{e(slide.note)}</p></div><div class="journey reveal">{steps}</div></div>'
        elif kind == "columns":
            body = (
                '<div class="three-cols reveal">'
                + "".join(
                    f'<article><span class="index">{i:02d}</span><h3>{e(heading_text(block.label))}</h3><p>{e(block.text)}</p></article>'
                    for i, block in enumerate(blocks, 1)
                )
                + "</div>"
                + note
            )
        elif kind == "metrics":
            body = (
                '<div class="metrics reveal">'
                + "".join(
                    f'<article class="metric"><span>{e(m.label)}</span><strong>{number(m.value)}</strong><p>{e(m.unit or "Unidad y período pendientes")}</p><small>{e(m.context)}</small></article>'
                    for m in content.metrics[:2]
                )
                + "</div>"
                + note
            )
            for metric in content.metrics[2:]:
                body += f'<p class="historical reveal">{e(metric.label)}: {number(metric.value)} {e(metric.unit or "con unidad por verificar")}. {e(metric.context)}</p>'
        elif kind == "system":
            nodes = "".join(
                f"<article><span>{i:02d}</span><h3>{e(block.label)}</h3><p>{e(block.text)}</p></article>"
                for i, block in enumerate(blocks, 1)
            )
            body = (
                f'<p class="system-intro reveal">{e(slide.intro)}</p>'
                f'<div class="system-diagram reveal">{nodes}</div>' + note
            )
        elif kind == "rows":
            body = (
                '<div class="quality-grid reveal">'
                + "".join(
                    f'<div class="quality-row"><b>{e(block.label)}</b><p>{e(block.text)}</p></div>'
                    for block in blocks
                )
                + "</div>"
                + note
            )
        elif kind == "split":
            body = (
                '<div class="split reveal"><div class="numbered">'
                + "".join(
                    f"<p><b>{e(block.label)}</b><span>{e(block.text)}</span></p>"
                    for block in blocks
                )
                + f'</div><aside class="statement"><span>Control de entrega</span><strong>{lines(heading_text(slide.note))}</strong></aside></div>'
            )
        elif kind == "roadmap":
            body = (
                '<div class="roadmap reveal">'
                + "".join(
                    f"<article><b>{i:02d}</b><h3>{e(heading_text(block.label))}</h3><p>{e(block.text)}</p></article>"
                    for i, block in enumerate(blocks, 1)
                )
                + "</div>"
                + note
            )
        else:
            deliverables = "".join(
                f"<p><span>{i:02d}</span>{e(text)}</p>"
                for i, text in enumerate(slide.intro.splitlines(), 1)
            )
            owners = "".join(
                f"<p><b>{e(block.label)}</b>{e(block.text)}</p>" for block in blocks
            )
            body = f'<div class="closing reveal"><div class="deliverable-stack">{deliverables}</div><div class="owners">{owners}</div></div><p class="closing-note reveal">{e(slide.note)}</p>'
        slides.append(f"""<section class="slide {"hero" if kind == "hero" else "type-" + kind}" aria-label="Diapositiva {index}" data-sources="{e(" ".join(slide.sources))}">
        <header><b class="brand"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M5 27V5h7l15 22V5" fill="none" stroke="currentColor" stroke-width="4"/></svg>{BRAND}</b><span>{e(transcript.project_name)}</span></header>
        <div class="slide-content"><div class="kicker reveal">{e(slide.kicker)}</div>
        <h2 class="reveal" data-edit-id="s{index}-title">{lines(heading_text(slide.title))}</h2>{body}</div>
        <footer><span>{"CASO FICTICIO / " if transcript.is_mock else ""}ENCUADRE EJECUTIVO / PARA REVISIÓN</span><b>{index:02d} / {total:02d}</b></footer></section>""")

    template = (ASSETS / "presentation.html").read_text()
    replacements = {
        "@@TITLE@@": e(f"{BRAND} / {transcript.project_name}"),
        "@@SLIDES@@": "\n".join(slides),
        "@@FONT_REGULAR@@": base64.b64encode(
            (ASSETS / "fonts/Lato-Regular.ttf").read_bytes()
        ).decode(),
        "@@FONT_BOLD@@": base64.b64encode(
            (ASSETS / "fonts/Lato-Bold.ttf").read_bytes()
        ).decode(),
        "@@STORAGE_KEY@@": "insumos-"
        + hashlib.sha256(content.model_dump_json().encode()).hexdigest()[:20],
        "@@VIEWPORT_CSS@@": (ASSETS / "viewport-base.css").read_text(),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    path.write_text(template, encoding="utf-8")


def render_presentation_pdf(html_path, pdf_path):
    """Print the exact HTML slides offline, one slide per PDF page."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        options = {"headless": True}
        executable = os.getenv("INSUMOS_BROWSER")
        if executable:
            options["executable_path"] = executable
        browser = pw.chromium.launch(**options)
        try:
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080}, reduced_motion="reduce"
            )
            context.set_offline(True)
            page = context.new_page()
            page.goto(Path(html_path).resolve().as_uri())
            page.evaluate("document.fonts.ready")
            page.emulate_media(media="print")
            page.add_style_tag(content="@page { size: 1920px 1080px; margin: 0; }")
            page.pdf(
                path=str(pdf_path),
                print_background=True,
                prefer_css_page_size=True,
                width="1920px",
                height="1080px",
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
        finally:
            browser.close()


def export_insumos(
    transcript: MeetingTranscript,
    content: MeetingInsumos,
    output: Path,
    *,
    status="awaiting_review",
):
    """Validate first, then publish complete files; no credentials or network access."""
    content.validate_transcript(transcript)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".insumos-", dir=output) as scratch:
        staging = Path(scratch)
        render_summary(staging / FILENAMES[0], transcript, content)
        render_brief(staging / FILENAMES[1], transcript, content)
        render_html(staging / FILENAMES[2], transcript, content)
        render_presentation_pdf(staging / FILENAMES[2], staging / FILENAMES[3])
        manifest = {
            "mock": transcript.is_mock,
            "source_sha256": transcript.fingerprint(),
            "preparation_status": status,
            "files": {
                name: hashlib.sha256((staging / name).read_bytes()).hexdigest()
                for name in FILENAMES
            },
        }
        for name in FILENAMES:
            (staging / name).replace(output / name)
        sources = output / "fuentes"
        sources.mkdir(exist_ok=True)
        (
            sources / "transcripcion-mock.md"
            if transcript.is_mock
            else sources / "transcripcion.md"
        ).write_text(transcript.as_markdown(), encoding="utf-8")
        (sources / "transcript.json").write_text(
            transcript.model_dump_json(indent=2), encoding="utf-8"
        )
        (sources / "preparacion.json").write_text(
            content.model_dump_json(indent=2), encoding="utf-8"
        )
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output / "README.md").write_text(
            f"# {transcript.project_name}\n\n"
            + (
                "Caso ficticio de demostración; no representa un encargo real.\n\n"
                if transcript.is_mock
                else "Borrador preparado a partir de la reunión de origen.\n\n"
            )
            + "- `resumen-reunion.pdf`: resumen completo, generado con ReportLab.\n"
            + "- `ficha-proyecto.pdf`: ficha ejecutiva del proyecto, generado con ReportLab.\n"
            + "- `presentacion.html`: presentación autónoma; abrir directamente en navegador.\n"
            + "- `presentacion.pdf`: las mismas diapositivas listas para compartir.\n"
            + "- `fuentes/`: transcripción y contenido estructurado utilizado para los tres insumos.\n"
            + "- `manifest.json`: hashes de origen y archivos, y estado de preparación.\n\n"
            + "La presentación funciona sin red. Flechas, espacio o gestos cambian diapositivas; "
            + "E activa la edición local y Ctrl/Cmd + S descarga una copia HTML.\n\n"
            + "Estado: pendiente de revisión humana. Para reproducir el escenario de Nike, "
            + "ejecutar `make insumos-mock` desde la raíz del repositorio.\n",
            encoding="utf-8",
        )
    return manifest
