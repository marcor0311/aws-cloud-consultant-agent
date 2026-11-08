"""Read-only catalog over the real Terraform baseline repository."""

from pathlib import Path

import yaml

from app.architecture.models import BaselineSelection


class BaselineCatalog:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def modules(self) -> list[dict]:
        aws = self.root / "aws"
        if not aws.is_dir():
            raise ValueError("No se encontró el catálogo de módulos baseline.")
        result = []
        for manifest in sorted(aws.glob("*/module.yaml")):
            module = yaml.safe_load(manifest.read_text(encoding="utf-8"))
            audit_path = manifest.with_name("audit-record.yaml")
            audit = (
                yaml.safe_load(audit_path.read_text(encoding="utf-8"))
                if audit_path.is_file()
                else {}
            )
            result.append(
                {
                    **module,
                    "path": manifest.parent.relative_to(self.root).as_posix(),
                    "implementation_review": audit.get("implementation_review"),
                    "production_approval": audit.get("production_approval"),
                    "aws_integration_validation": audit.get(
                        "aws_integration_validation"
                    ),
                }
            )
        return result

    def validate(self, selections: list[BaselineSelection]) -> None:
        catalog = {item["module_id"]: item for item in self.modules()}
        for selection in selections:
            actual = catalog.get(selection.module_id)
            if not actual:
                raise ValueError(f"Módulo baseline inexistente: {selection.module_id}.")
            if selection.candidate_version != actual["candidate_version"]:
                raise ValueError(
                    f"Versión incorrecta para {selection.module_id}; consultar el catálogo."
                )
            profiles = {profile["name"] for profile in actual.get("profiles", [])}
            if selection.profile not in profiles:
                raise ValueError(
                    f"Perfil inexistente para {selection.module_id}: {selection.profile}."
                )
            expected = (
                "approved"
                if actual.get("production_approval") == "approved"
                else "draft"
            )
            if selection.approval_status != expected:
                raise ValueError(
                    f"El estado declarado de {selection.module_id} no coincide con su auditoría."
                )
