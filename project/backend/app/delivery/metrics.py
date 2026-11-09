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
