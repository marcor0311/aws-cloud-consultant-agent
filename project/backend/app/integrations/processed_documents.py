"""Persist corporate exports for the worker; rendering belongs to insumos_export."""

import base64
import hashlib
import json
import re
import tempfile
from pathlib import Path

from app.integrations.insumos_export import export_insumos
from app.preparation.deliveries import files_digest
from app.preparation.processing import (
    CORPORATE_CONTRACT,
    ProcessedMeeting,
)
from app.preparation.processing import (
    CORPORATE_FILENAMES as FILENAMES,
)


class ProcessedDocuments:
    def __init__(self, store, root):
        self.store, self.root = store, Path(root).resolve()

    def __call__(self, state):
        case_id, revision = state["case_id"], state["revision"]
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,119}", case_id):
            raise ValueError("Identificador de proyecto inválido.")
        package = ProcessedMeeting.model_validate(state["package"])
        key = f"processed-files:{case_id}:{revision}"
        target = self.root / case_id
        saved = self.store.get(key)
        if saved:
            if any(
                not Path(f["path"]).is_file()
                or hashlib.sha256(Path(f["path"]).read_bytes()).hexdigest()
                != f["sha256"]
                for f in saved["documents"]
            ):
                raise ValueError(
                    "Los documentos locales cambiaron; requieren una nueva revisión."
                )
            if state.get("status") == "ready_for_stage_2":
                self.store.put(
                    f"approved-package:{case_id}:{revision}",
                    "approved-package",
                    {
                        "case_id": case_id,
                        "revision": revision,
                        "contents": {
                            f["name"]: base64.b64encode(
                                Path(f["path"]).read_bytes()
                            ).decode("ascii")
                            for f in saved["documents"]
                        },
                    },
                )
            return saved
        self.root.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or (
            target.exists()
            and any(
                p.name not in {*FILENAMES, "resumen-ejecutivo.pdf", ".DS_Store"}
                or p.is_symlink()
                for p in target.iterdir()
            )
        ):
            raise ValueError(
                "La carpeta de documentos contiene archivos ajenos; no se reemplaza."
            )
        with tempfile.TemporaryDirectory(
            prefix=".preparation-", dir=self.root
        ) as temporary:
            staging = Path(temporary) / "documents"
            staging.mkdir()
            source = self.store.get(f"transcript:{case_id}") or {}
            transcript, content = package.corporate_insumos(
                case_id,
                state["transcript"],
                is_synthetic=bool(source.get("is_synthetic"))
                or source.get("source") == "manual_synthetic",
            )
            export_insumos(
                transcript,
                content,
                staging,
                status=state["status"],
                transcript_text=state["transcript"],
                include_sources=False,
            )
            documents = [
                {
                    "name": name,
                    "path": str(target / name),
                    "media_type": "text/html"
                    if name.endswith(".html")
                    else "application/pdf",
                    "sha256": hashlib.sha256((staging / name).read_bytes()).hexdigest(),
                }
                for name in FILENAMES
            ]
            if target.exists():
                target.rename(Path(temporary) / "previous")
            staging.rename(target)
        value = {
            "case_id": case_id,
            "revision": revision,
            "directory": str(target),
            "contract": CORPORATE_CONTRACT,
            "documents": documents,
        }
        self.store.put(key, "processed-files", value)
        # Downstream receives the exact exported bytes after explicit approval.
        files = [{"name": f["name"], "sha256": f["sha256"]} for f in documents]
        self.store.put(
            f"artifact-files:{case_id}:{revision}",
            "artifact-files",
            {
                "case_id": case_id,
                "revision": revision,
                "files": files,
                "files_sha256": files_digest(files),
                "artifact_sha256": hashlib.sha256(
                    json.dumps(state["package"], sort_keys=True).encode()
                ).hexdigest(),
                "source_directory": str(target),
                "contract": CORPORATE_CONTRACT,
            },
        )
        return value
