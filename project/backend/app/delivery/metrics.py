"""Elapsed active time uses interval unions; actor effort may overlap."""

from app.delivery.models import PhaseTiming

PHASES = (
    "discovery",
    "prioritization",
    "architecture",
    "finops",
    "engineering",
    "report",
)


def duration_union(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return sum((end - start).total_seconds() for start, end in merged)


def calculate_metrics(timings: list[PhaseTiming]) -> dict:
    result = []
    for timing in timings:
        active = [a for a in timing.activities if a.kind != "wait"]
        waits = [a for a in timing.activities if a.kind == "wait"]
        active_seconds = duration_union([(a.started_at, a.ended_at) for a in active])
        classified = duration_union(
            [(a.started_at, a.ended_at) for a in timing.activities]
        )
        lead = (timing.handed_off_at - timing.accepted_at).total_seconds()
        result.append(
            {
                "phase": timing.phase,
                "provenance": timing.provenance,
                "lead_time_seconds": lead,
                "process_time_seconds": sum(
                    (a.ended_at - a.started_at).total_seconds() for a in active
                ),
                "active_elapsed_seconds": active_seconds,
                # Waiting excludes time where another actor is actively working.
                "wait_seconds": classified - active_seconds,
                "unclassified_seconds": max(0, lead - classified),
                "human_effort_seconds": sum(
                    (a.ended_at - a.started_at).total_seconds()
                    for a in active
                    if a.actor_type == "human"
                ),
                "agent_effort_seconds": sum(
                    (a.ended_at - a.started_at).total_seconds()
                    for a in active
                    if a.actor_type == "agent"
                ),
                "rework_effort_seconds": sum(
                    (a.ended_at - a.started_at).total_seconds()
                    for a in active
                    if a.kind == "rework"
                ),
                "reported_wait_effort_seconds": sum(
                    (a.ended_at - a.started_at).total_seconds() for a in waits
                ),
            }
        )
    present = {t.phase for t in timings}
    return {
        "phases": result,
        "missing_phases": [phase for phase in PHASES if phase not in present],
        "global_lead_time_seconds": None,
        "note": "No se infiere el Lead Time global sumando fases ni se reemplazan tiempos faltantes por cero. El esfuerzo humano/agente puede solaparse; no equivale a duración transcurrida.",
    }


def case_metrics(recorded: dict, captured_at: float) -> dict:
    """Read measured workflow sessions; parent/detail intervals never add twice.

    The workflow has no explicit wait/rework intervals. Keep those measurements
    unknown instead of relabelling gaps or multiplying rework cycles by time.
    """
    from datetime import UTC, datetime

    aliases = {
        "discovery": {"stage-1", "preparation", "calendar-tools"},
        "prioritization": {"stage-2", "project-opening"},
        **{phase: {f"stage-{n}"} for n, phase in enumerate(PHASES[2:], 3)},
    }

    def union(spans):
        return duration_union(
            [
                (datetime.fromtimestamp(a, UTC), datetime.fromtimestamp(b, UTC))
                for a, b in spans
                if b >= a
            ]
        )

    result = []
    for name, names in aliases.items():
        phases = [p for p in recorded["phases"] if p["phase"] in names]
        primary = next((p for p in phases if p["phase"].startswith("stage-")), None)
        # Stage 1's project boundary includes work before preparation began.
        bounds = recorded.get("stage_1") if name == "discovery" else None
        bounds = bounds or primary
        start = (
            bounds["opened_at" if "opened_at" in bounds else "accepted_at"]
            if bounds
            else None
        )
        finish = bounds.get("completed_at") if bounds else None
        end = finish if finish is not None else captured_at
        sessions = [s for s in recorded["sessions"] if s["phase"] in names]
        spans = [
            (s, max(start, s["started_at"]), min(end, s["ended_at"]))
            for s in sessions
            if start is not None
            and s["ended_at"] is not None
            and s["ended_at"] > start
            and s["started_at"] < end
        ]
        active = union([(a, b) for _, a, b in spans]) if spans else None

        def effort(actor_type):
            selected = [(s, a, b) for s, a, b in spans if s["actor_type"] == actor_type]
            return (
                sum(
                    union([(a, b) for s, a, b in selected if s["actor"] == actor])
                    for actor in {s["actor"] for s, _, _ in selected}
                )
                if spans
                else None
            )

        human, agent = effort("human"), effort("agent")
        result.append(
            {
                "phase": name,
                "provenance": "recorded_workflow",
                "lead_time_seconds": end - start if start is not None else None,
                "in_progress": start is not None and finish is None,
                "process_time_seconds": human + agent if spans else None,
                "active_elapsed_seconds": active,
                "human_effort_seconds": human,
                "agent_effort_seconds": agent,
                "wait_seconds": None,
                "rework_effort_seconds": None,
                "unclassified_seconds": end - start - (active or 0)
                if start is not None
                else None,
                "open_sessions": sum(s["ended_at"] is None for s in sessions),
                "source_phases": [p["phase"] for p in phases],
            }
        )
    return {
        "phases": result,
        "missing_phases": [
            p["phase"] for p in result if p["lead_time_seconds"] is None
        ],
        "global_lead_time_seconds": None,
        "rework_cycles": recorded["rework_cycles"],
        "handoffs": recorded["handoffs"],
        "note": "PT es esfuerzo registrado por actor; duración activa une intervalos sin duplicar fases de detalle. Espera y retrabajo de fase sin intervalos explícitos: sin medición. La espera entre entregas se muestra por separado. Sesiones abiertas no acreditan esfuerzo terminado. Un expediente ficticio sigue siendo ficticio aunque sus intervalos estén medidos.",
    }
