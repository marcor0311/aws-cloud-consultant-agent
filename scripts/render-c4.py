"""Publish the C4Context model as a deliberately laid-out, dependency-free SVG.

The .mmd file owns names, types and relationships. This renderer owns only the
composition: C4 person silhouettes, system boxes, colors and orthogonal routes.
"""

import ast
import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "http://www.w3.org/2000/svg"
INK = "#172b4d"
MUTED = "#526178"
LINE = "#526178"
COLORS = {
    "Person": "#08427b",
    "Person_Ext": "#686868",
    "System": "#1168bd",
    "System_Ext": "#64748b",
}

# Each position is the body rectangle; a person's head extends above it.
BOXES = {
    "chat": (100, 160, 260, 130),
    "usuario": (490, 160, 220, 130),
    "codigo": (840, 160, 260, 130),
    "github": (60, 440, 240, 130),
    "plataforma": (420, 430, 360, 150),
    "google": (900, 440, 240, 130),
    "cliente": (490, 730, 220, 120),
}
# Polyline points, label center, and label alignment.
ROUTES = {
    ("usuario", "chat"): ([(490, 225), (360, 225)], (425, 209), "middle"),
    ("usuario", "codigo"): ([(710, 225), (840, 225)], (775, 209), "middle"),
    ("chat", "plataforma"): (
        [(230, 290), (230, 352), (510, 352), (510, 430)],
        (370, 334),
        "middle",
    ),
    ("codigo", "plataforma"): (
        [(970, 290), (970, 352), (690, 352), (690, 430)],
        (830, 334),
        "middle",
    ),
    ("plataforma", "github"): ([(420, 505), (300, 505)], (360, 487), "middle"),
    ("plataforma", "google"): ([(780, 505), (900, 505)], (840, 487), "middle"),
    ("cliente", "plataforma"): ([(600, 678), (600, 580)], (618, 633), "start"),
}


def read_model(path):
    nodes, relationships = {}, {}
    declaration = re.compile(r"\s*(Person(?:_Ext)?|System(?:_Ext)?|Rel)\((.*)\)\s*")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = declaration.fullmatch(line)
        if not match:
            continue
        kind, arguments = match.groups()
        # Native C4 aliases are unquoted identifiers; decode only quoted values.
        fields = next_fields(arguments)
        if kind == "Rel":
            start, end, label, *technology = fields
            relationships[start, end] = (label, technology[0] if technology else "")
        else:
            alias, label, description = fields
            nodes[alias] = (kind, label, description)
    if set(nodes) != set(BOXES) or set(relationships) != set(ROUTES):
        raise ValueError("C4 model changed: update the layout and routes explicitly.")
    return nodes, relationships


def next_fields(arguments):
    # Read identifiers and string literals without evaluating code or splitting
    # descriptions at their commas.
    fields = []
    for value in ast.parse(f"({arguments},)", mode="eval").body.elts:
        if isinstance(value, ast.Name):
            fields.append(value.id)
        elif isinstance(value, ast.Constant) and isinstance(value.value, str):
            fields.append(value.value)
        else:
            raise TypeError("C4 declarations must contain aliases and strings.")
    return fields


def element(parent, name, **attributes):
    return ET.SubElement(
        parent,
        f"{{{NS}}}{name}",
        {key.replace("_", "-"): str(value) for key, value in attributes.items()},
    )


def text(parent, x, y, value, size=14, color=INK, weight="400", anchor="middle"):
    node = element(
        parent,
        "text",
        x=x,
        y=y,
        font_size=size,
        fill=color,
        font_weight=weight,
        text_anchor=anchor,
    )
    node.text = html.unescape(value)
    return node


def draw_node(parent, alias, model):
    kind, label, description = model
    x, y, width, height = BOXES[alias]
    center = x + width / 2
    person = kind.startswith("Person")
    group = element(parent, "g", id=alias)
    element(
        group,
        "rect",
        x=x,
        y=y,
        width=width,
        height=height,
        rx=22 if person else 5,
        fill=COLORS[kind],
    )
    if person:
        element(group, "circle", cx=center, cy=y - 26, r=26, fill=COLORS[kind])
    text(
        group,
        center,
        y + 38,
        re.sub(r"<br\s*/?>", " ", label),
        size=19 if alias == "plataforma" else 18,
        color="white",
        weight="600",
    )
    text(
        group,
        center,
        y + 61,
        "[Person]" if person else "[Software System]",
        size=12,
        color="#e8eef5",
    )
    lines = re.split(r"<br\s*/?>", description)
    for index, line in enumerate(lines):
        text(group, center, y + 89 + index * 20, line, color="white")


def main():
    root = Path(__file__).resolve().parents[1]
    nodes, relationships = read_model(root / "docs/c4-context.mmd")
    ET.register_namespace("", NS)
    svg = ET.Element(
        f"{{{NS}}}svg",
        {
            "viewBox": "0 0 1200 930",
            "width": "1200",
            "height": "930",
            "role": "img",
            "aria-labelledby": "title description",
            "font-family": "Arial, Helvetica, sans-serif",
            "style": "max-width:100%;height:auto;background:white",
        },
    )
    element(
        svg, "title", id="title"
    ).text = "AWS Cloud Consultant Agent: contexto C4 nivel 1"
    element(svg, "desc", id="description").text = (
        "El equipo usa ChatGPT o Claude y Codex o Claude Code para consumir el "
        "sistema multiagente por MCP. El sistema utiliza las API de GitHub y "
        "Google. El cliente gestiona sus reuniones con el sistema."
    )
    element(svg, "rect", width=1200, height=930, fill="white")
    definitions = element(svg, "defs")
    marker = element(
        definitions,
        "marker",
        id="arrow",
        viewBox="0 0 10 10",
        refX=9,
        refY=5,
        markerWidth=7,
        markerHeight=7,
        orient="auto-start-reverse",
    )
    element(marker, "path", d="M0 0 L10 5 L0 10 Z", fill=LINE)

    text(
        svg, 60, 47, "AWS Cloud Consultant Agent", size=25, weight="600", anchor="start"
    )
    text(
        svg,
        60,
        73,
        "C4 nivel 1: contexto objetivo",
        size=14,
        color=MUTED,
        anchor="start",
    )
    element(svg, "line", x1=60, y1=94, x2=1140, y2=94, stroke="#dce3eb")

    for connection, (label, technology) in relationships.items():
        points, (x, y), anchor = ROUTES[connection]
        path = "M" + " L".join(f"{px},{py}" for px, py in points)
        element(
            svg,
            "path",
            d=path,
            fill="none",
            stroke=LINE,
            stroke_width=1.6,
            marker_end="url(#arrow)",
        )
        lines = re.split(r"<br\s*/?>", label)
        for index, line in enumerate(lines):
            baseline = y - (len(lines) - 1 - index) * 18
            text(svg, x, baseline, line, size=13, color=MUTED, anchor=anchor)
        if technology:
            text(svg, x, y + 35, f"[{technology}]", size=12, color=MUTED, anchor=anchor)

    for alias, model in nodes.items():
        draw_node(svg, alias, model)

    element(svg, "line", x1=60, y1=881, x2=1140, y2=881, stroke="#dce3eb")
    for x, kind, label in (
        (60, "Person", "Persona interna"),
        (285, "Person_Ext", "Persona externa"),
        (510, "System", "Sistema en estudio"),
        (795, "System_Ext", "Sistema externo"),
    ):
        element(svg, "rect", x=x, y=900, width=12, height=12, rx=2, fill=COLORS[kind])
        text(svg, x + 21, 911, label, size=12, color=MUTED, anchor="start")

    ET.indent(svg, space="  ")
    target = root / "docs/c4-context.svg"
    ET.ElementTree(svg).write(target, encoding="unicode")
    print(f"C4 diagram generated: {target.relative_to(root)}")


if __name__ == "__main__":
    main()
