"""Bind exported files to a persisted preparation revision, without inferring approval."""

import hashlib
import json
import re

SCRIPT_NAME = "speaker-notes.md"


def bundle_path(case_id, revision):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,119}", case_id) or revision < 1:
        raise ValueError("Expediente o revisión inválidos.")
    return f"approved/{case_id}/v{revision}"


def files_digest(files):
    return hashlib.sha256(
        json.dumps(sorted(files, key=lambda f: f["name"]), sort_keys=True).encode()
    ).hexdigest()


class PreparationDeliveries:
    def __init__(self, store):
        self.store = store

    def presentation_files(self, case_id, revision, package):
        staged = self.store.get(f"presentation-files:{case_id}:{revision}")
        digest = hashlib.sha256(
            json.dumps(package, sort_keys=True).encode()
        ).hexdigest()
        if not staged or staged["artifact_sha256"] != digest:
            raise ValueError(
                "Registrar los cinco archivos de esta revisión antes de aprobar la presentación."
            )
        return staged["files"]

    def stage(self, case_id, revision, files, *, source_directory=""):
        """Record the five presentation inputs before their manager approval."""
        artifact = self.store.get(f"artifact:{case_id}:{revision}")
        if (
            not artifact
            or artifact["package"].get("speaker_notes")
            or len(files) != 5
            or len({f["name"] for f in files}) != 5
            or any(f["name"] == SCRIPT_NAME for f in files)
        ):
            raise ValueError(
                "La presentación requiere cinco archivos y su revisión sin guion."
            )
        value = {
            "case_id": case_id,
            "revision": revision,
            "files": files,
            "artifact_sha256": hashlib.sha256(
                json.dumps(artifact["package"], sort_keys=True).encode()
            ).hexdigest(),
            "source_directory": source_directory,
        }
        key = f"presentation-files:{case_id}:{revision}"
        with self.store.lock(key):
            previous = self.store.get(key)
            if previous:
                if previous["artifact_sha256"] != value[
                    "artifact_sha256"
                ] or files_digest(previous["files"]) != files_digest(files):
                    raise ValueError(
                        "La presentación ya tiene otros archivos; requiere nueva revisión."
                    )
                return previous
            if not previous:
                self.store.put(key, "presentation-files", value)
        return value

    def export_payload(self, case_id, revision):
        status = self.store.get(f"status:{case_id}")
        artifact = self.store.get(f"artifact:{case_id}:{revision}")
        handoff = self.store.handoff(f"{case_id}:stage-1:stage-2:v{revision}")
        if (
            not status
            or status["status"] != "ready_for_stage_2"
            or status["revision"] != revision
            or not artifact
            or not handoff
            or handoff["artifact_sha256"]
            != hashlib.sha256(
                json.dumps(artifact["package"], sort_keys=True).encode()
            ).hexdigest()
        ):
            raise ValueError(
                "Exportar requiere la revisión vigente aprobada, incluido el guion."
            )
        approval = artifact.get("presentation_approval", {})
        presentation = self.store.get(
            f"presentation-files:{case_id}:{approval.get('revision')}"
        )
        if (
            not presentation
            or presentation["artifact_sha256"] != approval.get("artifact_sha256")
            or files_digest(presentation["files"]) != approval.get("files_sha256")
        ):
            raise ValueError(
                "Faltan archivos vinculados a la aprobación; registrar los archivos y volver a aprobar la presentación."
            )
        text = artifact["documents"].get(SCRIPT_NAME, "")
        if not text.strip() or not artifact["package"].get("speaker_notes", "").strip():
            raise ValueError("La revisión aprobada no tiene guion.")
        script = text.encode("utf-8")
        return [
            *presentation["files"],
            {"name": SCRIPT_NAME, "sha256": hashlib.sha256(script).hexdigest()},
        ], script

    def bind(
        self,
        case_id,
        revision,
        files,
        *,
        approval_reference="",
        provenance="generated",
        source_directory="",
    ):
        artifact = self.store.get(f"artifact:{case_id}:{revision}")
        if (
            not artifact
            or len(files) not in {4, 5, 6}
            or len({f["name"] for f in files}) != len(files)
        ):
            raise ValueError(
                "La entrega requiere una revisión persistida y archivos distintos."
            )
        package_sha = hashlib.sha256(
            json.dumps(artifact["package"], sort_keys=True).encode()
        ).hexdigest()
        key = f"artifact-files:{case_id}:{revision}"
        value = {
            "case_id": case_id,
            "revision": revision,
            "files": files,
            "files_sha256": files_digest(files),
            "artifact_sha256": package_sha,
            "approval_reference": approval_reference,
            "provenance": provenance,
            "recorded_at": self.store.clock(),
            "historical_occurred_at": None,
        }
        with self.store.lock(key):
            previous = self.store.get(key)
            if previous:
                if (previous["files_sha256"], previous["artifact_sha256"]) != (
                    value["files_sha256"],
                    package_sha,
                ):
                    raise ValueError(
                        "La revisión ya tiene otros archivos; requiere nueva revisión."
                    )
                return previous
            if len(files) != 6:
                raise ValueError(
                    "Las nuevas entregas requieren seis archivos, incluido el guion aprobado."
                )
            if not source_directory:
                raise ValueError("La entrega requiere el directorio de exportación.")
            expected, _script = self.export_payload(case_id, revision)
            if files_digest(files) != files_digest(expected):
                raise ValueError(
                    "Los archivos o el guion no corresponden a la revisión aprobada."
                )
            value.update(
                bundle_path=bundle_path(case_id, revision),
                presentation_approval=artifact["presentation_approval"],
                source_directory=source_directory,
            )
            self.store.put(key, "artifact-files", value)
            self.store.event(
                "files-bound:" + hashlib.sha256(key.encode()).hexdigest(),
                case_id,
                "preparation.files_bound",
                value,
            )
        return value
