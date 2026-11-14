"""Validate approvals and execute a recoverable opening without deciding business policy."""

from app.project_opening.models import OpeningRequest
from app.project_opening.ports import OpeningRepository
from app.workflow.ports import WorkflowExecution


class OpeningService:
    def __init__(
        self,
        repository: OpeningRepository,
        execution: WorkflowExecution,
        validate_files,
        validate_board,
    ):
        self.repository = repository
        self.execution = execution
        self.validate_files = validate_files
        self.validate_board = validate_board

    def register(self, value):
        request = OpeningRequest.model_validate(value, context={"stored_legacy": True})
        if len(request.files) < 6:
            try:
                existing = self.repository.get(request.case_id)
            except ValueError:
                raise ValueError(
                    "Las nuevas aperturas requieren seis archivos, incluido el guion aprobado."
                ) from None
            if existing["request_sha256"] != request.fingerprint():
                raise ValueError(
                    "La apertura anterior tiene otra decisión; conciliar sin reemplazarla."
                )
        self.validate_files(request.files, request.case_id)
        source = self.repository.preparation_delivery(
            request.case_id, [f.model_dump() for f in request.files]
        )
        record = self.repository.reserve(request)
        return self.repository.accept_preparation(record, source)

    def queue(self):
        return self.repository.queue()

    def get(self, case_id):
        return self.repository.get(case_id)

    def audit(self, case_id):
        return self.repository.audit(case_id)

    def preflight(self, case_id):
        record = self.get(case_id)
        if record["status"] == "declined":
            raise ValueError("El proyecto fue rechazado en Dirección.")
        self.repository.validate_preparation(record)
        self.validate_files(
            OpeningRequest.model_validate(
                {
                    key: record[key]
                    for key in OpeningRequest.model_fields
                    if key in record
                },
                context={"stored_legacy": True},
            ).files,
            case_id,
        )
        certificate = self.validate_board(case_id)
        return {
            key: record[key]
            for key in (
                "case_id",
                "title",
                "request_sha256",
                "budget",
                "architect",
                "work",
                "files",
            )
        } | {"approval_sha256": certificate["digest"]}

    def run(self, case_id):
        with self.repository.lock(case_id):
            record = self.get(case_id)
            if record["status"] == "declined":
                raise ValueError("El proyecto fue rechazado en Dirección.")
            self.repository.validate_preparation(record)
            self.validate_files(
                OpeningRequest.model_validate(
                    {
                        key: record[key]
                        for key in OpeningRequest.model_fields
                        if key in record
                    },
                    context={"stored_legacy": True},
                ).files,
                case_id,
            )
            certificate = self.validate_board(case_id)
            thread = f"opening:{case_id}:board:{certificate['digest']}"
            snapshot = self.execution.inspect(thread)
            if (
                record["status"] == "delivered"
                and record.get("board_approval", {}).get("digest")
                == certificate["digest"]
            ):
                if not record.get("pull_request", {}).get("merged"):
                    raise ValueError("legacy_opening_requires_reconciliation")
                self.repository.accept_board(case_id, certificate)
                return record
            with self.repository.work(case_id):
                if not snapshot.state:
                    self.execution.start(thread, {"case_id": case_id})
                elif snapshot.runnable:
                    self.execution.continue_run(thread)
                else:
                    raise ValueError(
                        "El checkpoint requiere conciliación antes de continuar."
                    )
            return self.get(case_id)

    def run_next(self):
        pending = [
            r for r in self.queue() if r["status"] not in {"delivered", "declined"}
        ]
        return self.run(pending[0]["case_id"]) if pending else {"status": "idle"}
