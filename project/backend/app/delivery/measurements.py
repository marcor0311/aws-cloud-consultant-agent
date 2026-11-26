"""Evidence-backed measurement corrections; gaps never become inferred work."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.delivery.engineering_models import Digest, digest
from app.delivery.models import Contract, Text
from app.persistence.delivery import DeliveryConflict

Stage = Literal["stage-1", "stage-2", "stage-3", "stage-4", "stage-5", "stage-6"]


class PhaseCorrection(Contract):
    phase: Stage
    accepted_at: AwareDatetime
    completed_at: AwareDatetime | None = None


class SessionCorrection(Contract):
    session_id: Text
    ended_at: AwareDatetime | None = None
    kind: Literal["work", "wait", "rework"]


class HandoffCorrection(Contract):
    handoff_id: Text
    accepted_at: AwareDatetime


class MeasurementDecision(Contract):
    reconciliation_id: UUID
    case_id: Text
    expected_sha256: Digest
    reference: Text
    detail: Text
    phases: list[PhaseCorrection] = Field(default_factory=list, max_length=6)
    sessions: list[SessionCorrection] = Field(default_factory=list, max_length=100)
    handoffs: list[HandoffCorrection] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def changes(self):
        if not (self.phases or self.sessions or self.handoffs):
            raise ValueError("Indicar correcciones respaldadas por evidencia")
        for items, field in (
            (self.phases, "phase"),
            (self.sessions, "session_id"),
            (self.handoffs, "handoff_id"),
        ):
            if len({getattr(i, field) for i in items}) != len(items):
                raise ValueError("Una medición está repetida")
        return self


def reconciliation_status(recorded):
    state = {
        "case_id": recorded["case_id"],
        "phases": sorted(
            [
                {k: p[k] for k in ("phase", "accepted_at", "completed_at")}
                for p in recorded["phases"]
            ],
            key=lambda p: p["phase"],
        ),
        "sessions": sorted(recorded["sessions"], key=lambda s: s["id"]),
        "handoffs": sorted(
            [
                {
                    k: v
                    for k, v in h.items()
                    if k not in {"wait_seconds", "pending_acceptance"}
                }
                for h in recorded["handoffs"]
            ],
            key=lambda h: h["id"],
        ),
    }
    issues = []
    phase_map = {p["phase"]: p for p in state["phases"]}
    for n in range(1, 7):
        name = f"stage-{n}"
        if name not in phase_map:
            issues.append({"kind": "missing_phase", "reference": name})
        elif phase_map[name]["completed_at"] is None:
            issues.append({"kind": "phase_in_progress", "reference": name})
    for session in state["sessions"]:
        if session["ended_at"] is None:
            issues.append({"kind": "open_session", "reference": session["id"]})
        if session.get("kind") not in {"work", "wait", "rework"}:
            issues.append({"kind": "unclassified_session", "reference": session["id"]})
        phase = phase_map.get(session["phase"])
        if (
            not phase
            or session["started_at"] < phase["accepted_at"]
            or (
                session["ended_at"] is not None
                and phase["completed_at"] is not None
                and session["ended_at"] > phase["completed_at"]
            )
        ):
            issues.append({"kind": "session_outside_phase", "reference": session["id"]})
    for handoff in state["handoffs"]:
        if handoff["accepted_at"] is None:
            issues.append({"kind": "handoff_not_accepted", "reference": handoff["id"]})
    return {
        "state_sha256": digest(state),
        "issues": issues,
        "status": "requires_reconciliation"
        if issues
        else "recorded_measurements_reconciled",
        "note": "La conciliación revisa registros existentes; no acredita actividad nunca medida ni convierte brechas en espera.",
    }


class MeasurementService:
    def __init__(self, store, operator):
        self.store, self.operator = store, operator

    def _owned(self, case_id):
        if not any(
            p["case_id"] == case_id for p in self.store.project_list(self.operator)
        ):
            raise ValueError("Expediente inexistente o de otro responsable")

    def get(self, case_id):
        self._owned(case_id)
        return {
            "case_id": case_id,
            **reconciliation_status(self.store.metrics(case_id)),
            "history": [
                r
                for r in self.store.list("measurement-reconciliation")
                if r["decision"]["case_id"] == case_id
            ],
        }

    def reconcile(self, decision):
        self._owned(decision.case_id)
        key = f"measurement-reconciliation:{decision.case_id}:{decision.reconciliation_id}"
        value = decision.model_dump(mode="json")
        with self.store.lock(f"process:{decision.case_id}"):
            prior = self.store.get(key)
            if prior:
                if prior["decision"] != value or prior["operator"] != self.operator:
                    raise DeliveryConflict(
                        "El identificador corresponde a otra conciliación"
                    )
                return self.get(decision.case_id)
            process = self.store.get(f"process:{decision.case_id}") or {}
            if process.get("status") == "completed":
                raise DeliveryConflict(
                    "El expediente está cerrado; sus mediciones no se modifican"
                )
            recorded = self.store.metrics(decision.case_id)
            before = reconciliation_status(recorded)
            if before["state_sha256"] != decision.expected_sha256:
                raise DeliveryConflict(
                    "Las mediciones cambiaron; consultar y conciliar la versión vigente"
                )
            now = self.store.clock()
            proposed = {p["phase"]: dict(p) for p in recorded["phases"]}
            for correction in decision.phases:
                start = correction.accepted_at.timestamp()
                end = (
                    correction.completed_at.timestamp()
                    if correction.completed_at
                    else None
                )
                if start > now or end is not None and not start <= end <= now:
                    raise ValueError("Límites de fase inválidos o futuros")
                proposed[correction.phase] = {
                    **proposed.get(
                        correction.phase,
                        {
                            "case_id": decision.case_id,
                            "phase": correction.phase,
                            "manager_id": self.operator,
                            "issue_url": "",
                        },
                    ),
                    "accepted_at": start,
                    "completed_at": end,
                }
            work = {s["id"]: dict(s) for s in recorded["sessions"]}
            for correction in decision.sessions:
                session = work.get(correction.session_id)
                if not session:
                    raise ValueError("La sesión no pertenece al expediente")
                if (
                    session.get("evidence_reference", "").startswith(
                        "engineering-evidence:"
                    )
                    and session["kind"] != correction.kind
                ):
                    raise DeliveryConflict(
                        "La clasificación técnica proviene de su evidencia; no se sobrescribe"
                    )
                end = (
                    correction.ended_at.timestamp()
                    if correction.ended_at
                    else session["ended_at"]
                )
                if end is None or not session["started_at"] <= end <= now:
                    raise ValueError("La sesión requiere un cierre válido y no futuro")
                session.update(ended_at=end, kind=correction.kind)
            for session in work.values():
                if session["phase"] not in {
                    c.phase for c in decision.phases
                } and session["id"] not in {c.session_id for c in decision.sessions}:
                    continue
                phase = proposed.get(session["phase"])
                if (
                    not phase
                    or session["started_at"] < phase["accepted_at"]
                    or (
                        session["ended_at"] is not None
                        and session["ended_at"]
                        > (
                            phase["completed_at"]
                            if phase["completed_at"] is not None
                            else now
                        )
                    )
                ):
                    raise ValueError("La corrección deja una sesión fuera de su fase")
            transfers = {h["id"]: h for h in recorded["handoffs"]}
            for correction in decision.handoffs:
                transfer = transfers.get(correction.handoff_id)
                if (
                    not transfer
                    or not transfer["created_at"]
                    <= correction.accepted_at.timestamp()
                    <= now
                ):
                    raise ValueError(
                        "La recepción del handoff es inválida o pertenece a otro expediente"
                    )
            record = {
                "decision": value,
                "operator": self.operator,
                "at": now,
                "before": before,
                "original": recorded,
            }
            self.store.reconcile_measurements(
                key,
                record,
                [proposed[c.phase] for c in decision.phases],
                [
                    {
                        "session_id": c.session_id,
                        "ended_at": work[c.session_id]["ended_at"],
                        "kind": c.kind,
                    }
                    for c in decision.sessions
                ],
                [
                    {
                        "id": c.handoff_id,
                        "accepted_at": c.accepted_at.timestamp(),
                        "accepted_by": transfers[c.handoff_id]["to_actor"],
                    }
                    for c in decision.handoffs
                ],
            )
            return self.get(decision.case_id)
