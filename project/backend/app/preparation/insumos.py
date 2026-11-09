"""Source-bound meeting content shared by PDF and HTML exporters."""

import hashlib
import json
import unicodedata
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.preparation.models import Citation, ExecutivePackage, Finding, Slide


def integer_words(value: int) -> str:
    """Canonical Spanish cardinal for literal integer evidence below one million."""
    small = (
        "cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece "
        "catorce quince dieciseis diecisiete dieciocho diecinueve veinte veintiuno "
        "veintidos veintitres veinticuatro veinticinco veintiseis veintisiete "
        "veintiocho veintinueve"
    ).split()
    if not 0 <= value < 1_000_000:
        return ""
    if value < 30:
        return small[value]
    if value < 100:
        tens = "treinta cuarenta cincuenta sesenta setenta ochenta noventa".split()
        return tens[value // 10 - 3] + (" y " + small[value % 10] if value % 10 else "")
    if value == 100:
        return "cien"
    if value < 1000:
        hundreds = (
            "ciento doscientos trescientos cuatrocientos quinientos seiscientos "
            "setecientos ochocientos novecientos"
        ).split()
        return hundreds[value // 100 - 1] + (
            " " + integer_words(value % 100) if value % 100 else ""
        )
    thousands = value // 1000
    prefix = "" if thousands == 1 else integer_words(thousands) + " "
    prefix = prefix.replace("veintiuno ", "veintiun ").replace(" y uno ", " y un ")
    return prefix + "mil" + (" " + integer_words(value % 1000) if value % 1000 else "")


def metric_matches_quote(value: int, quote: str) -> bool:
    digits = "".join(c for c in quote if c.isdigit())
    if digits:
        return str(value) == digits
    normalized = unicodedata.normalize("NFKD", " ".join(quote.casefold().split()))
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    # Feminine hundreds are also valid for personas or inscripciones.
    return normalized in {
        integer_words(value),
        integer_words(value).replace("ientos", "ientas"),
    } and bool(normalized)


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Segment(InputModel):
    id: str
    speaker: str
    at: AwareDatetime
    text: str = Field(min_length=1)


class MeetingTranscript(InputModel):
    id: str
    title: str
    project_name: str
    client: str
    is_mock: bool
    started_at: AwareDatetime
    ended_at: AwareDatetime
    participants: list[str]
    segments: list[Segment] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_meeting(self):
        if self.ended_at <= self.started_at:
            raise ValueError("El fin debe ser posterior al inicio.")
        previous = self.started_at
        seen = set()
        for segment in self.segments:
            if segment.id in seen or not previous <= segment.at <= self.ended_at:
                raise ValueError("IDs o tiempos de transcripción inválidos.")
            seen.add(segment.id)
            previous = segment.at
        return self

    def fingerprint(self):
        raw = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def as_text(self):
        return "\n".join(
            f"[{s.id} | {s.at.strftime('%H:%M:%S')}] {s.speaker}: {s.text}"
            for s in self.segments
        )

    def as_markdown(self):
        label = (
            "SIMULACIÓN FICTICIA - no corresponde a una reunión real"
            if self.is_mock
            else "Transcripción de reunión"
        )
        return (
            f"# {self.title}\n\n{label}\n\n"
            f"Cliente del escenario: {self.client}\n\n"
            f"Inicio: {self.started_at.isoformat()}\n\n"
            f"Fin: {self.ended_at.isoformat()}\n\n"
            + "\n".join(f"- {person}" for person in self.participants)
            + "\n\n## Conversación\n\n"
            + "\n\n".join(
                f"### {s.id} - {s.at.strftime('%H:%M:%S')} - {s.speaker}\n\n{s.text}"
                for s in self.segments
            )
            + "\n"
        )


class Point(InputModel):
    text: str = Field(min_length=1)
    sources: list[str] = Field(min_length=1)
    status: Literal["confirmed", "proposed", "pending"] = "confirmed"


class Topic(InputModel):
    title: str
    points: list[Point]


class ProjectFact(Point):
    label: str


class Metric(InputModel):
    label: str
    value: int = Field(gt=0)
    unit: str | None
    context: str
    source: str
    quote: str


class Action(InputModel):
    task: str
    owner: str
    due: str
    sources: list[str] = Field(min_length=1)


class DeckBlock(InputModel):
    label: str
    text: str


class AdvisoryItem(InputModel):
    """Consultant-authored development, grounded in needs rather than agreements."""

    label: str
    text: str = Field(min_length=1)
    sources: list[str] = Field(min_length=1)
    status: Literal["proposed"] = "proposed"


class ConsultantProposal(InputModel):
    concept: AdvisoryItem
    experience: list[AdvisoryItem] = Field(min_length=1)
    solution: list[AdvisoryItem] = Field(min_length=1)
    delivery: list[AdvisoryItem] = Field(min_length=1)
    acceptance: list[AdvisoryItem] = Field(min_length=1)
    safeguards: list[AdvisoryItem] = Field(min_length=1)

    def items(self):
        return [
            self.concept,
            *self.experience,
            *self.solution,
            *self.delivery,
            *self.acceptance,
            *self.safeguards,
        ]


class ExecutiveReading(InputModel):
    purpose: str
    recommendation: AdvisoryItem
    outcomes: list[AdvisoryItem] = Field(min_length=1, max_length=3)
    oversight: AdvisoryItem


class DeckSlide(InputModel):
    kind: Literal[
        "hero",
        "journey",
        "columns",
        "metrics",
        "rows",
        "split",
        "roadmap",
        "closing",
        "system",
        "executive",
    ]
    kicker: str
    title: str
    intro: str = ""
    blocks: list[DeckBlock] = Field(default_factory=list, max_length=3)
    note: str = ""
    sources: list[str] = Field(min_length=1)


class MeetingInsumos(InputModel):
    source_sha256: str
    summary: str
    summary_sources: list[str]
    objectives: list[Point]
    topics: list[Topic]
    scope_in: list[Point]
    scope_out: list[Point]
    journey: list[str]
    metrics: list[Metric] = Field(min_length=1, max_length=3)
    decisions: list[Point]
    actions: list[Action]
    risks: list[Point]
    questions: list[Point]
    success: list[Point]
    budget: Point
    timeline: Point
    presentation: list[DeckSlide] = Field(min_length=1, max_length=30)
    proposal: ConsultantProposal | None = None
    facts: list[ProjectFact] = Field(default_factory=list)
    executive: ExecutiveReading | None = None

    def validate_transcript(self, transcript: MeetingTranscript):
        if self.source_sha256 != transcript.fingerprint():
            raise ValueError("El contenido no corresponde a esta transcripción.")
        source = {s.id: s.text for s in transcript.segments}
        references = [*self.summary_sources]
        points = [
            *self.facts,
            *self.objectives,
            *self.scope_in,
            *self.scope_out,
            *self.decisions,
            *self.risks,
            *self.questions,
            *self.success,
            self.budget,
            self.timeline,
            *(point for topic in self.topics for point in topic.points),
        ]
        for point in points:
            references.extend(point.sources)
        for action in self.actions:
            references.extend(action.sources)
        for slide in self.presentation:
            references.extend(slide.sources)
        if self.proposal:
            for item in self.proposal.items():
                references.extend(item.sources)
        if self.executive:
            for item in [
                self.executive.recommendation,
                *self.executive.outcomes,
                self.executive.oversight,
            ]:
                references.extend(item.sources)
        if not references or any(key not in source for key in references):
            raise ValueError("Hay contenido sin referencia válida a la reunión.")
        for metric in self.metrics:
            if not metric.quote or metric.quote not in source.get(metric.source, ""):
                raise ValueError("La cifra requiere una cita literal de la reunión.")
            if not metric_matches_quote(metric.value, metric.quote):
                raise ValueError("La cifra no coincide con la cita literal.")
        return self

    def executive_package(self, transcript: MeetingTranscript):
        """Use the existing preparation graph/review contract without replacing it."""
        self.validate_transcript(transcript)
        sources = {s.id: s.text for s in transcript.segments}

        def finding(point):
            return Finding(
                text=point.text,
                status={
                    "confirmed": "confirmed",
                    "proposed": "inferred",
                    "pending": "unknown",
                }[point.status],
                citations=[
                    Citation(source_id="transcript", quote=sources[key])
                    for key in point.sources
                ],
            )

        package = ExecutivePackage(
            summary=self.summary,
            needs=[finding(point) for point in self.objectives],
            requirements=[finding(point) for point in self.scope_in],
            budget=finding(self.budget),
            timeline=finding(self.timeline),
            risks=[finding(point) for point in self.risks],
            open_questions=[point.text for point in self.questions],
            related_projects=[],
            presentation=[
                Slide(title=topic.title, bullets=[p.text for p in topic.points])
                for topic in self.topics
            ],
            speaker_notes="\n".join(point.text for point in self.decisions),
        )
        return package.validate_sources({"transcript": transcript.as_text()}, set())


def meeting_date(value: datetime):
    value = value.astimezone(ZoneInfo("America/Costa_Rica"))
    months = (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    )
    return f"{value.day} de {months[value.month - 1]} de {value.year}"
