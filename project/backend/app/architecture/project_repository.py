"""Read approved Agent 2 inputs and stage Agent 3 artifacts in a project repo."""

import hashlib
import json
import subprocess
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class RepositoryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ApprovedInput(RepositoryContract):
    document_type: Literal[
        "requirements",
        "constraints",
        "decision",
        "budget",
        "discovery_evidence",
        "board_record",
    ]
    path: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: (
        Literal[
            "text/markdown",
            "text/html",
            "application/json",
            "application/yaml",
            "application/pdf",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def path_is_an_approved_phase_input(self):
        path = PurePosixPath(self.path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or path.suffix.lower()
            not in {".md", ".html", ".json", ".yaml", ".yml", ".pdf"}
            or not (
                self.path.startswith("docs/01-discovery/")
                or self.path.startswith("docs/02-board/")
            )
        ):
            raise ValueError("El insumo debe pertenecer a discovery o board.")
        expected_media_types = {
            ".md": "text/markdown",
            ".html": "text/html",
            ".json": "application/json",
            ".yaml": "application/yaml",
            ".yml": "application/yaml",
            ".pdf": "application/pdf",
        }
        if (
            self.media_type
            and self.media_type != expected_media_types[path.suffix.lower()]
        ):
            raise ValueError("El media_type no coincide con la extensión del insumo.")
        return self


class ApprovalEvidence(RepositoryContract):
    evidence_type: Literal["test", "human"]
    decision: Literal["approved"]
    document_path: str = Field(min_length=1, max_length=500)
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: AwareDatetime
    simulated: bool = False
    decision_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    signature_verification: Literal[
        "not_declared",
        "declared_by_source",
        "independently_verified",
    ] = "not_declared"


class BoardBudgetLine(RepositoryContract):
    name: str = Field(min_length=1, max_length=300)
    amount: Decimal = Field(ge=0, max_digits=24, decimal_places=6)


class BoardBudget(RepositoryContract):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    total: Decimal = Field(gt=0, max_digits=24, decimal_places=6)
    accepted: Literal[True]
    lines: list[BoardBudgetLine] = Field(min_length=1, max_length=100)
    conditions: str = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def lines_match_total(self):
        if sum((line.amount for line in self.lines), Decimal("0")) != self.total:
            raise ValueError("Las partidas del presupuesto no suman el total aprobado.")
        return self


class BoardFile(RepositoryContract):
    name: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BoardMember(RepositoryContract):
    slack_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)


class BoardVote(RepositoryContract):
    choice: Literal["approve"]
    action_ts: str = Field(min_length=1, max_length=100)
    voted_at: AwareDatetime
    received_at: AwareDatetime
    request_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature_verified: bool


class BoardReceipt(RepositoryContract):
    channel: str = Field(min_length=1, max_length=200)
    ts: str = Field(min_length=1, max_length=100)


class BoardRecord(RepositoryContract):
    id: str = Field(min_length=1, max_length=200)
    case_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=500)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget: BoardBudget
    files: list[BoardFile] = Field(min_length=1, max_length=100)
    members: list[BoardMember] = Field(min_length=1, max_length=100)
    votes: dict[str, BoardVote] = Field(min_length=1, max_length=100)
    rule: Literal["unanimity"]
    opened_at: float | AwareDatetime
    closed_at: AwareDatetime
    status: Literal["approved"]
    is_simulated: bool
    team_id: str = Field(min_length=1, max_length=200)
    app_id: str = Field(min_length=1, max_length=200)
    channel_id: str = Field(min_length=1, max_length=200)
    receipt: BoardReceipt
    review_url: str
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def unanimous_votes_are_coherent(self):
        member_ids = [member.slack_id for member in self.members]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("Los miembros de junta no pueden repetirse.")
        if set(self.votes) != set(member_ids):
            raise ValueError("La unanimidad requiere un voto por cada miembro.")
        if not all(vote.signature_verified for vote in self.votes.values()):
            raise ValueError("El acta no declara verificadas todas las firmas.")
        return self


def approved_input_digest(revision: int, inputs: list[ApprovedInput]) -> str:
    payload = {
        "approved_revision": revision,
        "inputs": [
            item.model_dump(mode="json")
            for item in sorted(inputs, key=lambda item: item.path)
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ArchitectureProjectHandoff(RepositoryContract):
    contract_version: Literal["1.1", "1.2"] = "1.1"
    source_stage: Literal[2] = 2
    case_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,59}$")
    repository_path: str = Field(min_length=1, max_length=1000)
    repository_url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+(?:\.git)?$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    architecture_issue_url: str = Field(
        pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$"
    )
    approved_revision: int = Field(ge=1)
    approved_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inputs: list[ApprovedInput] = Field(min_length=1, max_length=100)
    approval: ApprovalEvidence

    @model_validator(mode="after")
    def references_are_unique_and_same_repository(self):
        paths = [item.path for item in self.inputs]
        if len(paths) != len(set(paths)):
            raise ValueError("Los insumos aprobados no pueden repetirse.")
        document_types = [item.document_type for item in self.inputs]
        if self.contract_version == "1.1":
            required = {"requirements", "constraints", "decision", "budget"}
            if set(document_types) != required or len(document_types) != len(required):
                raise ValueError(
                    "La entrega requiere requirements, constraints, decision y budget."
                )
            if any(item.media_type is not None for item in self.inputs):
                raise ValueError(
                    "ArchitectureProjectHandoff 1.1 no declara media_type."
                )
        else:
            discovery = [
                item
                for item in self.inputs
                if item.document_type == "discovery_evidence"
            ]
            board = [
                item for item in self.inputs if item.document_type == "board_record"
            ]
            if not discovery or len(board) != 1:
                raise ValueError(
                    "La entrega 1.2 requiere evidencias discovery y un board_record."
                )
            if any(item.media_type is None for item in self.inputs):
                raise ValueError("ArchitectureProjectHandoff 1.2 requiere media_type.")
        repository = self.repository_url.removesuffix(".git")
        if not self.architecture_issue_url.startswith(repository + "/issues/"):
            raise ValueError("El issue debe pertenecer al repositorio del proyecto.")
        decision_type = "decision" if self.contract_version == "1.1" else "board_record"
        decision = next(
            item for item in self.inputs if item.document_type == decision_type
        )
        if (
            self.approval.document_path != decision.path
            or self.approval.document_sha256 != decision.sha256
        ):
            raise ValueError("La aprobación no corresponde al documento de decisión.")
        if self.contract_version == "1.1":
            if self.approved_artifact_sha256 != approved_input_digest(
                self.approved_revision, self.inputs
            ):
                raise ValueError(
                    "El hash aprobado no corresponde al manifiesto de entrada."
                )
        else:
            if not self.approval.decision_digest:
                raise ValueError("La entrega 1.2 requiere el digest del acta.")
            expected_type = "test" if self.approval.simulated else "human"
            if self.approval.evidence_type != expected_type:
                raise ValueError("La simulación debe conservarse en la aprobación.")
            if self.approval.signature_verification != "declared_by_source":
                raise ValueError(
                    "La entrega 1.2 solo acredita firmas declaradas por la fuente."
                )
        return self


class ProjectRepositoryBridge:
    REQUIRED_DIRECTORIES = (
        "docs/01-discovery",
        "docs/02-board",
        "docs/03-architecture",
        "docs/04-finops",
        "docs/05-engineering",
        "docs/06-executive",
        "infra",
        "tests",
    )

    @staticmethod
    def _git(root: Path, *args: str) -> bytes:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
        )
        if result.returncode:
            raise ValueError("No se pudo leer el commit aprobado del proyecto.")
        return result.stdout

    @classmethod
    def _root(cls, path: str) -> Path:
        root = Path(path).resolve()
        if not root.is_dir() or not (root / ".git").exists():
            raise ValueError("La entrega no apunta a un repositorio Git local.")
        missing = [
            name for name in cls.REQUIRED_DIRECTORIES if not (root / name).is_dir()
        ]
        if missing:
            raise ValueError("El repositorio no conserva la estructura del template.")
        return root

    def read(self, handoff):
        delivery = ArchitectureProjectHandoff.model_validate(handoff)
        root = self._root(delivery.repository_path)
        self._git(root, "cat-file", "-e", f"{delivery.source_commit}^{{commit}}")
        documents = []
        raw_by_path = {}
        for approved in delivery.inputs:
            raw = self._git(root, "show", f"{delivery.source_commit}:{approved.path}")
            raw_by_path[approved.path] = raw
            digest = hashlib.sha256(raw).hexdigest()
            if digest != approved.sha256:
                raise ValueError("Un insumo no coincide con su SHA-256 aprobado.")
            binary = approved.media_type == "application/pdf"
            content = None
            if not binary:
                try:
                    content = raw.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ValueError(
                        "Los insumos textuales deben ser UTF-8."
                    ) from error
            documents.append(
                {
                    "document_type": approved.document_type,
                    "path": approved.path,
                    "sha256": digest,
                    "media_type": approved.media_type,
                    "content": content,
                    "binary_omitted": binary,
                }
            )
        board_validation = None
        budget = None
        if delivery.contract_version == "1.2":
            board_input = next(
                item for item in delivery.inputs if item.document_type == "board_record"
            )
            try:
                board_payload = json.loads(raw_by_path[board_input.path])
                board = BoardRecord.model_validate(board_payload)
            except (json.JSONDecodeError, ValueError) as error:
                raise ValueError("El board_record aprobado no es válido.") from error
            if board.case_id != delivery.case_id:
                raise ValueError("El acta corresponde a otro expediente.")
            if board.request_sha256 != delivery.approved_artifact_sha256:
                raise ValueError(
                    "El request_sha256 del acta no coincide con la entrega."
                )
            if board.digest != delivery.approval.decision_digest:
                raise ValueError("El digest del acta no coincide con la aprobación.")
            if board.is_simulated != delivery.approval.simulated:
                raise ValueError("La condición simulada del acta no coincide.")
            if board.closed_at != delivery.approval.approved_at:
                raise ValueError(
                    "La fecha de aprobación no coincide con el cierre del acta."
                )
            discovery_inputs = [
                item
                for item in delivery.inputs
                if item.document_type == "discovery_evidence"
            ]
            for approved_file in board.files:
                candidates = [
                    item
                    for item in discovery_inputs
                    if item.path == approved_file.name
                    or PurePosixPath(item.path).name == approved_file.name
                ]
                if len(candidates) != 1 or candidates[0].sha256 != approved_file.sha256:
                    raise ValueError(
                        "Los archivos del acta no coinciden con las evidencias aprobadas."
                    )
            if len(board.files) != len(discovery_inputs):
                raise ValueError(
                    "El acta debe enumerar todas las evidencias discovery."
                )
            board_validation = {
                "record_id": board.id,
                "request_sha256": board.request_sha256,
                "decision_digest": board.digest,
                "status": board.status,
                "simulated": board.is_simulated,
                "vote_rule": board.rule,
                "members": len(board.members),
                "votes": len(board.votes),
                "signatures": "declared_by_source",
                "cryptographic_verification_performed": False,
            }
            budget = board.budget.model_dump(mode="json")
        return {
            "contract_version": delivery.contract_version,
            "case_id": delivery.case_id,
            "project_id": delivery.project_id,
            "repository_path": str(root),
            "repository_url": delivery.repository_url,
            "source_commit": delivery.source_commit,
            "architecture_issue_url": delivery.architecture_issue_url,
            "approved_revision": delivery.approved_revision,
            "approved_artifact_sha256": delivery.approved_artifact_sha256,
            "approval": delivery.approval.model_dump(mode="json"),
            "board_validation": board_validation,
            "budget": budget,
            "documents": documents,
            "input_id": delivery.source_commit,
        }

    def publish(self, root_path: str, revision: int, documents: dict[str, str | bytes]):
        root = self._root(root_path)
        target = root / "docs" / "03-architecture" / "versions" / f"v{revision:03d}"
        manifest = {
            "contract_version": "1.0",
            "revision": revision,
            "files": [
                {
                    "path": filename,
                    "sha256": hashlib.sha256(
                        content.encode("utf-8") if isinstance(content, str) else content
                    ).hexdigest(),
                }
                for filename, content in sorted(documents.items())
            ],
        }
        expected = {**documents, "manifest.json": json.dumps(manifest, indent=2) + "\n"}
        if target.exists():
            actual = {
                path.relative_to(target).as_posix(): (
                    path.read_bytes()
                    if isinstance(
                        expected.get(path.relative_to(target).as_posix()), bytes
                    )
                    else path.read_text(encoding="utf-8")
                )
                for path in target.rglob("*")
                if path.is_file()
            }
            if actual != expected:
                raise ValueError("La revisión publicada es inmutable.")
            return {"status": "duplicate", "path": str(target), **manifest}
        target.mkdir(parents=True)
        for filename, content in expected.items():
            relative = PurePosixPath(filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Nombre de artefacto inválido.")
            destination = target.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                destination.write_bytes(content)
            else:
                destination.write_text(content, encoding="utf-8", newline="\n")
        return {"status": "published", "path": str(target), **manifest}
