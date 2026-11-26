"""Hash local engineering exports under one explicitly configured directory."""

import json
from hashlib import sha256
from pathlib import Path


class EngineeringFiles:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def read(self, files):
        result = []
        for file in files:
            relative = Path(file.path)
            path = (self.root / relative).resolve()
            if (
                relative.is_absolute()
                or relative.drive
                or ".." in relative.parts
                or not path.is_relative_to(self.root)
            ):
                raise ValueError(
                    "El archivo debe permanecer dentro del directorio de insumos"
                )
            allowed = {
                ".md",
                ".pdf",
                ".xlsx",
                ".csv",
                ".json",
                ".txt",
                ".log",
                ".tf",
                ".hcl",
                ".html",
                ".yaml",
                ".yml",
            }
            if path.suffix.lower() not in allowed or any(
                word in path.name.lower()
                for word in ("secret", "credential", "token", "tfstate", "tfplan")
            ):
                raise ValueError(
                    "No se admiten credenciales, planes, estado ni archivos fuera del contrato"
                )
            suffix = path.suffix.lower()
            if file.role == "cost_workbook" and suffix != ".xlsx":
                raise ValueError("El respaldo de costos debe ser un archivo XLSX")
            if file.role == "calculator_export" and suffix not in {".csv", ".pdf"}:
                raise ValueError("El respaldo de la calculadora debe ser CSV o PDF")
            if file.role == "implementation" and suffix not in {".tf", ".hcl", ".json"}:
                raise ValueError(
                    "La implementación debe contener configuración Terraform"
                )
            if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("Archivo ausente o mayor de 16 MiB")
            data = path.read_bytes()
            if sha256(data).hexdigest() != file.sha256:
                raise ValueError("El archivo no corresponde al SHA-256 declarado")
            if suffix == ".json":
                try:
                    value = json.loads(data)
                except (ValueError, UnicodeError):
                    value = None
                if isinstance(value, dict) and (
                    {"planned_values", "resource_changes", "prior_state"} & value.keys()
                    or "terraform_version" in value
                    and {"resources", "values", "outputs"} & value.keys()
                ):
                    raise ValueError(
                        "No adjuntar el plan ni el estado Terraform; registrar solo sus hashes"
                    )
            result.append((file.model_dump(mode="json"), data))
        if sum(len(data) for _, data in result) > 64 * 1024 * 1024:
            raise ValueError("El paquete supera 64 MiB")
        return result
