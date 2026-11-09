"""Readable board minutes plus structured vote evidence for docs/02-board/."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from app.project_opening.board import certificate_for


def local_date(value):
    return (
        datetime.fromisoformat(value)
        .astimezone(ZoneInfo("America/Costa_Rica"))
        .strftime("%d/%m/%Y %H:%M:%S %Z")
    )


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def board_documents(certificate):
    if certificate_for(certificate) != certificate:
        raise ValueError("El acta y su evidencia no coinciden.")
    labels = {"approve": "A favor", "reject": "En contra", "abstain": "Abstención"}
    approved = sum(v["choice"] == "approve" for v in certificate["votes"].values())
    outcome = (
        "Aprobado por unanimidad"
        if certificate["status"] == "approved"
        else "No aprobado"
    )
    lines = [
        "# Acta de votación de junta directiva",
        "",
        "**SIMULACIÓN: miembros y votos ficticios; no constituye una aprobación real.**"
        if certificate["is_simulated"]
        else "Registro de la decisión emitida mediante la votación en Slack.",
        "",
        f"**Proyecto:** {certificate['title']}",
        f"**Resultado:** {outcome} ({approved}/{len(certificate['members'])} votos a favor)",
        "**Regla:** unanimidad de todos los miembros registrados; abstenciones y votos en contra no aprueban.",
        f"**Cierre:** {local_date(certificate['closed_at'])}",
        f"**Convocatoria:** {local_date(datetime.fromtimestamp(certificate['opened_at'], ZoneInfo('UTC')).isoformat())}",
        f"**Expediente:** `{certificate['case_id']}`",
        f"**Votación:** `{certificate['id']}`",
        "",
        "## Participantes y votos",
        "",
        "| Miembro de junta | Identidad Slack | Voto | Fecha y hora (Costa Rica) |",
        "| --- | --- | --- | --- |",
    ]
    for member in certificate["members"]:
        vote = certificate["votes"][member["slack_id"]]
        lines.append(
            f"| {cell(member['name'])} | `{member['slack_id']}` | {labels[vote['choice']]} | {local_date(vote['voted_at'])} |"
        )
    budget = certificate["budget"]
    lines += [
        "",
        "## Presupuesto sometido a aprobación",
        "",
        f"**Total:** {budget['currency']} {budget['total']}",
        "",
    ]
    lines += [
        f"- {cell(item['name'])}: {budget['currency']} {item['amount']}"
        for item in budget["lines"]
    ]
    lines += [
        "",
        budget["conditions"],
        "",
        "## Insumos y versión aprobados",
        "",
        f"Huella de la decisión y su paquete: `{certificate['request_sha256']}`",
        "",
    ]
    lines += [
        f"- `{f['name']}` — SHA-256 `{f['sha256']}`" for f in certificate["files"]
    ]
    lines += [
        "",
        "## Evidencia de la votación",
        "",
        f"- Workspace: `{certificate['team_id']}`; aplicación: `{certificate['app_id']}`.",
        f"- Canal: `{certificate['channel_id']}`; mensaje: `{certificate['receipt']['ts']}`.",
        "- Cada voto conserva fecha de Slack, fecha de recepción y hash del cuerpo recibido con firma verificada.",
        "- Las fechas UTC completas y los recibos individuales se incluyen en el JSON adjunto.",
        f"- SHA-256 del certificado estructurado: `{certificate['digest']}`.",
        "- El registro acredita estos votos sobre esta versión; una lectura o reacción genérica no cuenta como aprobación.",
        "",
    ]
    stem = "docs/02-board/acta-junta-" + certificate["id"]
    return {
        stem + ".md": "\n".join(lines).encode(),
        stem + ".json": json.dumps(certificate, ensure_ascii=False, indent=2).encode(),
    }
