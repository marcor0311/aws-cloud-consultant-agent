"""Import local engineering packages and receipts without executing Terraform."""

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.bootstrap import create_engineering_runtime
from app.core.config import project_path
from app.delivery.engineering_models import (
    EngineeringEvidence,
    EngineeringIntake,
    EngineeringRelease,
    digest,
)
from app.persistence.delivery import DeliveryConflict
from app.persistence.locking import Busy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "manifest",
            "intake",
            "evidence",
            "status",
            "catalog",
            "release-manifest",
            "release",
        ],
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--intake-id", type=UUID)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=project_path("generated/engineering-inputs"),
    )
    args = parser.parse_args()
    if args.command not in ("status", "catalog") and args.input is None:
        parser.error("Indicar --input")
    if args.command in ("status", "catalog") and args.intake_id is None:
        parser.error("Indicar --intake-id")
    try:
        value = None
        if args.input:
            model = (
                EngineeringRelease
                if args.command in ("release", "release-manifest")
                else (
                    EngineeringEvidence
                    if args.command == "evidence"
                    else EngineeringIntake
                )
            )
            value = model.model_validate_json(args.input.read_bytes())
        if args.command == "release-manifest":
            print(json.dumps({"release_sha256": value.approval_digest()}))
            return
        if args.command == "manifest":
            print(
                json.dumps(
                    {
                        "architecture_sha256": value.approval_digest(3),
                        "finops_sha256": value.approval_digest(4),
                        "input_sha256": digest(value.model_dump(mode="json")),
                    }
                )
            )
            return
        runtime = create_engineering_runtime(
            os.getenv("WORKFLOW_DATABASE_URL", ""),
            args.artifact_root,
            os.getenv("ENGINEERING_OPERATOR", ""),
        )
        try:
            method = {
                "intake": runtime.service.register,
                "evidence": runtime.service.record_evidence,
                "release": runtime.service.record_release,
                "catalog": runtime.service.catalog,
                "status": runtime.service.get,
            }[args.command]
            result = method(
                args.intake_id if args.command in ("status", "catalog") else value
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            runtime.close()
    except (ValueError, LookupError, OSError, DeliveryConflict, Busy) as error:
        parser.exit(1, str(error) + "\n")
    except SQLAlchemyError:
        parser.exit(1, "Persistencia no disponible; revisar WORKFLOW_DATABASE_URL.\n")


if __name__ == "__main__":
    main()
