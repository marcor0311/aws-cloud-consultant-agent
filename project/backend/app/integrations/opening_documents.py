"""Load exact approved files; render one shared issue contract for every project."""

import hashlib
import json
import tempfile
from pathlib import Path
from string import Template

from app.integrations.board_documents import board_documents
from app.preparation.deliveries import PreparationDeliveries, bundle_path


def delivery_manifest(manifest):
    return json.dumps(
        {
            key: manifest[key]
            for key in ("case_id", "revision", "files", "presentation_approval")
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ).encode("utf-8")


class OpeningDocuments:
    def __init__(self, source_dir, issue_template, store=None):
        self.source_dir = Path(source_dir).resolve()
        self.issue_template = Path(issue_template)
        self.store = store

    def manifest(self, case_id, revision=None):
        if not self.store or not case_id:
            return None
        status = self.store.get(f"status:{case_id}")
        revision = revision or (status or {}).get("revision")
        return self.store.get(f"artifact-files:{case_id}:{revision}")

    def directory(self, manifest):
        directory = Path(
            (manifest or {}).get("source_directory") or self.source_dir
        ).resolve()
        if not manifest or not manifest.get("bundle_path"):
            return directory
        relative = bundle_path(manifest["case_id"], manifest["revision"])
        if manifest["bundle_path"] != relative:
            raise ValueError("El directorio del paquete requiere conciliación.")
        for part in Path(relative).parts:
            directory = directory / part
            if directory.is_symlink():
                raise ValueError(
                    "El directorio del paquete no admite enlaces simbólicos."
                )
        return directory

    def read(self, file, manifest=None):
        directory = self.directory(manifest)
        path = directory / file.name
        if path.is_symlink() or path.resolve().parent != directory.resolve():
            raise ValueError("Los insumos deben estar dentro del directorio aprobado.")
        data = path.read_bytes()
        if len(data) > 20_000_000 or hashlib.sha256(data).hexdigest() != file.sha256:
            raise ValueError(
                "El insumo cambió después de aprobarse o supera el límite."
            )
        return data

    def validate(self, files, case_id=None):
        manifest = self.manifest(case_id)
        for file in files:
            self.read(file, manifest)
        if manifest and manifest.get("bundle_path"):
            path = self.directory(manifest) / "manifest.json"
            if path.is_symlink() or path.read_bytes() != delivery_manifest(manifest):
                raise ValueError(
                    "El manifiesto local cambió después de exportarse; conciliar sin sobrescribirlo."
                )

    def export_preparation(self, case_id, revision):
        """Export exact approved bytes to a new revision directory, without overwrites."""
        from app.project_opening.models import ApprovedFile

        if not self.store:
            raise ValueError("Exportar requiere el almacén de preparación.")
        deliveries = PreparationDeliveries(self.store)
        with self.store.lock(f"export-package:{case_id}:{revision}"):
            files, script = deliveries.export_payload(case_id, revision)
            artifact = self.store.get(f"artifact:{case_id}:{revision}")
            previous = self.manifest(case_id, revision) or {}
            presentation = self.store.get(
                f"presentation-files:{case_id}:{artifact['presentation_approval']['revision']}"
            )
            metadata = {
                "case_id": case_id,
                "revision": revision,
                "files": files,
                "presentation_approval": artifact["presentation_approval"],
                "bundle_path": bundle_path(case_id, revision),
                "source_directory": previous.get("source_directory")
                or presentation.get("source_directory")
                or str(self.source_dir),
            }
            target = self.directory(metadata)
            contents = {
                file["name"]: self.read(
                    ApprovedFile.model_validate(file),
                    metadata
                    if target.exists()
                    else {"source_directory": metadata["source_directory"]},
                )
                for file in files[:-1]
            }
            contents[files[-1]["name"]] = script
            contents["manifest.json"] = delivery_manifest(metadata)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if {p.name for p in target.iterdir()} != set(contents) or any(
                    (target / name).is_symlink() or (target / name).read_bytes() != data
                    for name, data in contents.items()
                ):
                    raise ValueError(
                        "El paquete exportado cambió; conciliar sin sobrescribirlo."
                    )
            else:
                with tempfile.TemporaryDirectory(
                    prefix="approved-package-", dir=target.parent
                ) as temporary:
                    staging = Path(temporary) / "package"
                    staging.mkdir()
                    for name, data in contents.items():
                        (staging / name).write_bytes(data)
                    staging.rename(target)
            manifest = deliveries.bind(
                case_id, revision, files, source_directory=metadata["source_directory"]
            )
            return {**manifest, "directory": str(target)}

    def files(self, record):
        from app.project_opening.models import ApprovedFile

        manifest = self.manifest(
            record["case_id"], record.get("incoming_preparation", {}).get("revision")
        )
        files = {
            "docs/01-discovery/" + f["name"]: self.read(
                ApprovedFile.model_validate(f), manifest
            )
            for f in record["files"]
        }
        if manifest and manifest.get("bundle_path"):
            files["docs/01-discovery/manifest.json"] = delivery_manifest(manifest)
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
        manifest = self.manifest(
            record["case_id"], record.get("incoming_preparation", {}).get("revision")
        )
        if manifest and manifest.get("bundle_path"):
            links += (
                f"\n- [Manifiesto de entrega]({base}manifest.json) — revisión {manifest['revision']}, "
                f"SHA-256 `{hashlib.sha256(delivery_manifest(manifest)).hexdigest()}`"
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
