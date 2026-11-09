"""Register known local inputs without inventing a Calendar booking or past work."""


def start_local_preparation(runtime, case_id, transcript, *, provenance):
    service, store = runtime.service, runtime.store
    owner = store.get(f"owner:{case_id}")
    if owner and owner["manager_id"] != service.manager_id:
        raise ValueError("El expediente pertenece a otro responsable.")
    if not owner:
        store.put(
            f"owner:{case_id}",
            "owner",
            {"case_id": case_id, "manager_id": service.manager_id},
        )
    if not any(p["case_id"] == case_id for p in store.project_list(service.manager_id)):
        store.register_project(
            case_id,
            case_id,
            transcript.project_name,
            transcript.client,
            service.manager_id,
            is_fictitious=transcript.is_mock,
        )
    previous = store.get(f"local-transcript:{case_id}")
    if previous and previous["source_sha256"] != transcript.fingerprint():
        raise ValueError("El expediente ya tiene otra transcripción local.")
    if not previous:
        store.put(
            f"local-transcript:{case_id}",
            "transcript",
            {
                "case_id": case_id,
                "source_id": transcript.id,
                "source_sha256": transcript.fingerprint(),
                "text": transcript.as_text(),
                "is_fictitious": transcript.is_mock,
                "provenance": provenance,
                "recorded_at": store.clock(),
                "historical_occurred_at": None,
            },
        )
    runtime.process.ensure(case_id)
    runtime.process.internal(
        case_id,
        "local-transcript:" + transcript.fingerprint(),
        "transcript.available",
        provenance=provenance,
        is_fictitious=transcript.is_mock,
    )
    return service.start(
        case_id,
        "local-transcript:" + transcript.fingerprint(),
        transcript.as_text(),
        "reservas pagos contenido conectividad sistemas locales duplicados",
    )
