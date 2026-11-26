"""Read-only catalog over the real Terraform baseline repository."""

import subprocess
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

    def _module_at_commit(self, commit: str, module_id: str) -> dict:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "show",
                f"{commit}:aws/{module_id}/module.yaml",
            ],
            check=False,
            capture_output=True,
        )
        if result.returncode:
            raise ValueError(f"El commit baseline no contiene el módulo {module_id}.")
        try:
            return yaml.safe_load(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError) as error:
            raise ValueError("El manifiesto baseline fijado no es válido.") from error

    def validate(self, selections: list[BaselineSelection]) -> None:
        catalog = {item["module_id"]: item for item in self.modules()}
        for selection in selections:
            actual = catalog.get(selection.module_id)
            if not actual:
                raise ValueError(f"Módulo baseline inexistente: {selection.module_id}.")
            pinned = self._module_at_commit(selection.commit, selection.module_id)
            if selection.candidate_version != pinned["candidate_version"]:
                raise ValueError(
                    f"Versión incorrecta para {selection.module_id}; consultar el catálogo."
                )
            profiles = {profile["name"] for profile in pinned.get("profiles", [])}
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
