"""Load exact approved files; render one shared issue contract for every project."""

import hashlib
from pathlib import Path
from string import Template

from app.integrations.board_documents import board_documents


class OpeningDocuments:
    def __init__(self, source_dir, issue_template):
        self.source_dir = Path(source_dir).resolve()
        self.issue_template = Path(issue_template)

    def read(self, file):
        path = self.source_dir / file.name
        if path.is_symlink() or path.resolve().parent != self.source_dir:
            raise ValueError("Los insumos deben estar dentro del directorio aprobado.")
        data = path.read_bytes()
        if len(data) > 20_000_000 or hashlib.sha256(data).hexdigest() != file.sha256:
            raise ValueError(
                "El insumo cambió después de aprobarse o supera el límite."
            )
        return data

    def validate(self, files):
        for file in files:
            self.read(file)

    def files(self, record):
        from app.project_opening.models import ApprovedFile

        files = {
            "docs/01-discovery/" + f["name"]: self.read(ApprovedFile.model_validate(f))
            for f in record["files"]
        }
        # Prose and immutable evidence use long lines and transcript speaker labels.
        # Frontmatter titles do not count as a second Markdown H1.
        files[".markdownlint-cli2.jsonc"] = (
            '{"config":{"MD013":false,"MD036":false,'
            '"MD025":{"front_matter_title":""}}}\n'
        ).encode()
        template = self.issue_template.read_text()
        files[".github/ISSUE_TEMPLATE/architecture.md"] = template.encode()
        files["README.md"] = (
            f"# {record['title']}\n\n"
            f"Proyecto creado desde [{record['template_repository']}]"
            f"(https://github.com/{record['template_repository']}).\n\n"
            f"Proyecto de [{record['owner']}](https://github.com/{record['owner']}).\n\n"
            "Los insumos aprobados están en `docs/01-discovery/`. "
            "El diseño se documenta en `docs/03-architecture/` y se revisa mediante PR.\n"
        ).encode()
        if record.get("board_approval"):
            files.update(board_documents(record["board_approval"]))
        return files

    def issue(self, record):
        template = self.issue_template.read_text()
        budget = record["budget"]
        lines = "\n".join(
            f"- {line['name']}: {budget['currency']} {line['amount']}"
            for line in budget["lines"]
        )
        # Pin links to the approved commit, never to a mutable branch.
        base = (
            record["repository"]["url"]
            + "/blob/"
            + record["commit"]["sha"]
            + "/docs/01-discovery/"
        )
        links = "\n".join(
            f"- [{f['name']}]({base}{f['name']}) — SHA-256 `{f['sha256']}`"
            for f in record["files"]
        )
        values = {
            "project": record["title"],
            "architect": record["architect"],
            "budget": f"{budget['currency']} {budget['total']}\n\n{lines}\n\n{budget['conditions']}",
            "inputs": links,
            "marker": "<!-- meeting-assistant:"
            + record["case_id"]
            + ":"
            + record["request_sha256"]
            + " -->",
            **record["work"],
        }
        certificate = record.get("board_approval")
        if not certificate:
            raise ValueError("El encargo requiere el acta de aprobación de junta.")
        minutes_path = "docs/02-board/acta-junta-" + certificate["id"] + ".md"
        values["board_minutes"] = (
            "[Acta de votación]("
            + record["repository"]["url"]
            + "/blob/"
            + record["commit"]["sha"]
            + "/"
            + minutes_path
            + "). "
            + "SHA-256 del certificado: `"
            + certificate["digest"]
            + "`."
        )
        body = (
            template.split("---", 2)[2].lstrip()
            if template.startswith("---\n")
            else template
        )
        return Template(body).substitute(values), template
