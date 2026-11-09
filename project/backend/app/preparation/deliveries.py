"""Bind exported files to a persisted preparation revision, without inferring approval."""

import hashlib
import json


def files_digest(files):
    return hashlib.sha256(
        json.dumps(sorted(files, key=lambda f: f["name"]), sort_keys=True).encode()
    ).hexdigest()


class PreparationDeliveries:
    def __init__(self, store):
        self.store = store

    def bind(
        self, case_id, revision, files, *, approval_reference="", provenance="generated"
    ):
        artifact = self.store.get(f"artifact:{case_id}:{revision}")
        if (
            not artifact
            or len(files) not in {4, 5}
            or len({f["name"] for f in files}) != len(files)
        ):
            raise ValueError(
                "La entrega requiere una revisión persistida y cuatro o cinco archivos distintos."
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
            self.store.put(key, "artifact-files", value)
            self.store.event(
                "files-bound:" + hashlib.sha256(key.encode()).hexdigest(),
                case_id,
                "preparation.files_bound",
                value,
            )
        return value
