"""Validated, source-bound output from the preparation agent."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class OutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(OutputModel):
    source_id: str
    quote: str


class Finding(OutputModel):
    text: str
    status: Literal["confirmed", "inferred", "unknown"]
    citations: list[Citation]


class RelatedProject(OutputModel):
    project_id: str
    reason: str
    citations: list[Citation]


class Slide(OutputModel):
    title: str
    bullets: list[str]


class ExecutivePackage(OutputModel):
    summary: str
    needs: list[Finding]
    requirements: list[Finding]
    budget: Finding
    timeline: Finding
    risks: list[Finding]
    open_questions: list[str]
    related_projects: list[RelatedProject]
    presentation: list[Slide]
    speaker_notes: str

    def validate_sources(self, sources: dict[str, str], project_ids: set[str]):
        findings = [
            *self.needs,
            *self.requirements,
            self.budget,
            self.timeline,
            *self.risks,
        ]
        for finding in findings:
            if finding.status == "confirmed" and not any(
                citation.source_id == "transcript" for citation in finding.citations
            ):
                raise ValueError("Un dato confirmado requiere una cita de la reunión.")
        for project in self.related_projects:
            if project.project_id not in project_ids or not project.citations:
                raise ValueError("El antecedente debe existir y tener evidencia.")
            if any(
                not c.source_id.startswith(f"references/projects/{project.project_id}/")
                for c in project.citations
            ):
                raise ValueError("La evidencia debe corresponder al proyecto citado.")
        for item in [*findings, *self.related_projects]:
            for citation in item.citations:
                text = sources.get(citation.source_id)
                if not text or not citation.quote.strip() or citation.quote not in text:
                    raise ValueError("La cita no aparece en la fuente identificada.")
        return self

    def artifacts(self):
        def section(title, items):
            return (
                f"\n## {title}\n\n"
                + "\n".join(
                    f"- [{item.status}] {item.text}"
                    + "".join(
                        f"\n  - Fuente `{c.source_id}`: «{c.quote}»"
                        for c in item.citations
                    )
                    for item in items
                )
                + "\n"
            )

        summary = f"# Resumen ejecutivo — borrador\n\n{self.summary}\n"
        for title, findings in (
            ("Necesidades", self.needs),
            ("Requisitos", self.requirements),
            ("Presupuesto", [self.budget]),
            ("Plazos", [self.timeline]),
            ("Riesgos", self.risks),
        ):
            summary += section(title, findings)
        summary += "\n## Preguntas pendientes\n\n" + "\n".join(
            f"- {q}" for q in self.open_questions
        )
        summary += "\n\n## Antecedentes ficticios\n\n" + "\n".join(
            f"- {p.project_id}: {p.reason}" for p in self.related_projects
        )
        slides = "# Propuesta de presentación\n\n" + "\n\n".join(
            f"## {s.title}\n\n" + "\n".join(f"- {b}" for b in s.bullets)
            for s in self.presentation
        )
        documents = {
            "executive-summary.md": summary,
            "presentation.md": slides,
        }
        if self.speaker_notes.strip():
            documents["speaker-notes.md"] = "# Guion\n\n" + self.speaker_notes
        return documents
