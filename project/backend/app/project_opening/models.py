"""Naming and approval contracts; independent of providers and persistence."""

import hashlib
import re
import unicodedata
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PREFIX = "AWS Cloud Consulting Project"
TEMPLATE = "marcor0311/aws-cloud-consulting-project-template"


def slug(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    result = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    if not result:
        raise ValueError("El nombre debe contener letras o números.")
    return result


def project_identity(company, number, project_name):
    title = f"{PREFIX} {company.strip()} {number:02d} {project_name.strip()}"
    name = slug(title)
    if len(name) > 100:
        raise ValueError("El nombre del repositorio supera 100 caracteres.")
    return {"title": title, "repository_name": name}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BudgetLine(Input):
    name: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class Budget(Input):
    currency: Literal["USD"] = "USD"
    total: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    accepted: Literal[True]
    lines: list[BudgetLine] = Field(min_length=1)
    conditions: str = Field(min_length=1)

    @model_validator(mode="after")
    def consistent(self):
        if sum(line.amount for line in self.lines) != self.total:
            raise ValueError("Las partidas deben sumar el presupuesto total.")
        if len({line.name for line in self.lines}) != len(self.lines):
            raise ValueError("Las partidas del presupuesto deben ser distintas.")
        return self


class ApprovedFile(Input):
    name: str = Field(pattern=r"^[\w.-]+\.(pdf|html|md)$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ArchitectureWork(Input):
    context: str = Field(min_length=1, max_length=12000)
    scope: str = Field(min_length=1, max_length=12000)
    restrictions: str = Field(min_length=1, max_length=12000)
    deliverables: str = Field(min_length=1, max_length=12000)
    acceptance: str = Field(min_length=1, max_length=12000)


class OpeningRequest(Input):
    case_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,119}$")
    company: str = Field(min_length=1, max_length=60)
    project_name: str = Field(min_length=1, max_length=100)
    owner: str = Field(
        default="aws-cloud-consulting-group", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,38}$"
    )
    template_repository: str = Field(default=TEMPLATE, pattern=r"^[\w.-]+/[\w.-]+$")
    private: bool = False
    queue_position: int = Field(ge=1)
    architect: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,38}$")
    issue_assignee: str | None = Field(
        default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,38}$"
    )
    budget: Budget
    work: ArchitectureWork
    approved_by: str = Field(min_length=1, max_length=160)
    approval_reference: str = Field(min_length=1, max_length=1000)
    comments: str = Field(default="", max_length=12000)
    files: list[ApprovedFile] = Field(min_length=4, max_length=5)
    is_fictitious: bool = False

    @model_validator(mode="after")
    def unique_files(self):
        names = [f.name for f in self.files]
        if len(set(names)) != len(names) or not any(
            name.endswith(".md") for name in names
        ):
            raise ValueError("Se requieren insumos distintos, con transcripción.")
        if (
            sum(name.endswith(".pdf") for name in names) != len(names) - 2
            or sum(name.endswith(".html") for name in names) != 1
        ):
            raise ValueError(
                "Se requieren dos PDF, presentación HTML y transcripción; el quinto archivo debe ser la presentación PDF."
            )
        if len(names) == 5 and not any(
            name.endswith(".html") and name[:-5] + ".pdf" in names for name in names
        ):
            raise ValueError("La presentación PDF debe corresponder al archivo HTML.")
        slug(self.company)
        return self

    def fingerprint(self):
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()
